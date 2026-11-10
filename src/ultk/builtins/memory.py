"""Persistent namespace-isolated memory for ULTK."""
from __future__ import annotations
import asyncio, hashlib, json, math, re, sqlite3, time, uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable
from ultk.exceptions import ToolExecutionError
from ultk.models import ToolContext, ToolSpec
from ultk.builtins._common import object_schema

_WORD=re.compile(r"[^\W_]+",re.UNICODE)
_KINDS={"episodic","semantic","procedural"}
def _tokens(s:str)->list[str]:
    return [x.casefold() for x in _WORD.findall(s) if len(x)>1][:4000]
def _vector(s:str,n:int=256)->list[float]:
    v=[0.0]*n
    for word,count in Counter(_tokens(s)).items():
        h=int.from_bytes(hashlib.blake2b(word.encode(),digest_size=8).digest(),"little")
        v[h%n]+=count*(1 if (h>>8)&1 else -1)
    norm=math.sqrt(sum(x*x for x in v))
    return [x/norm for x in v] if norm else v
def _cos(a:list[float],b:list[float])->float:
    return max(0.0,min(1.0,sum(x*y for x,y in zip(a,b)))) if len(a)==len(b) else 0.0
def _fingerprint(s:str)->str:
    return hashlib.sha256(" ".join(s.casefold().split()).encode()).hexdigest()
def _metadata(value:Any)->dict[str,Any]:
    if not isinstance(value,dict): raise ToolExecutionError("metadata must be an object.")
    try: raw=json.dumps(value,ensure_ascii=False,allow_nan=False)
    except (TypeError,ValueError) as exc: raise ToolExecutionError("metadata must be JSON-safe.") from exc
    if len(raw.encode())>10000: raise ToolExecutionError("metadata exceeds 10 KB.")
    return value

class PersistentMemory:
    def __init__(self,database:str|Path,*,namespace:str,
                 embedder:Callable[[str],list[float]]|None=None,max_items:int=100000):
        if not isinstance(namespace,str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}",namespace):
            raise ValueError("namespace must be a safe host-defined identifier.")
        if not 1<=max_items<=2000000: raise ValueError("max_items out of range.")
        self.database=str(Path(database).expanduser().resolve()); self.namespace=namespace
        self.embedder=embedder; self.max_items=max_items
        Path(self.database).parent.mkdir(parents=True,exist_ok=True)
        with self.db() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript("""
            CREATE TABLE IF NOT EXISTS memory_items(
              id TEXT PRIMARY KEY, ns TEXT NOT NULL, sid TEXT NOT NULL, kind TEXT NOT NULL,
              scope TEXT NOT NULL, content TEXT NOT NULL, tags TEXT NOT NULL, metadata TEXT NOT NULL,
              confidence REAL NOT NULL, vector TEXT NOT NULL, fingerprint TEXT NOT NULL,
              created REAL NOT NULL, updated REAL NOT NULL, accesses INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS memory_ns_idx ON memory_items(ns,kind,updated DESC);
            CREATE INDEX IF NOT EXISTS memory_fp_idx ON memory_items(ns,fingerprint);
            CREATE TABLE IF NOT EXISTS memory_context(
              ns TEXT NOT NULL,sid TEXT NOT NULL,seq INTEGER NOT NULL,role TEXT NOT NULL,
              content TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(ns,sid,seq));
            """)
    @contextmanager
    def db(self):
        c = sqlite3.connect(self.database, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()
    def embedding(self,text:str)->list[float]:
        try: v=self.embedder(text) if self.embedder else _vector(text)
        except Exception as exc: raise ToolExecutionError("Embedding generation failed.") from exc
        if not isinstance(v,(list,tuple)) or not 8<=len(v)<=8192: raise ToolExecutionError("Invalid embedding dimensions.")
        v=[float(x) for x in v]
        if not all(math.isfinite(x) for x in v): raise ToolExecutionError("Embedding contains non-finite values.")
        norm=math.sqrt(sum(x*x for x in v))
        return [x/norm for x in v] if norm else v
    def context_append(self,session_id:str,role:str,content:str)->dict:
        if role not in {"system","user","assistant","tool"} or not isinstance(content,str) or not content.strip() or len(content)>20000:
            raise ToolExecutionError("Invalid context role/content.")
        with self.db() as c:
            seq=c.execute("SELECT COALESCE(MAX(seq),0)+1 n FROM memory_context WHERE ns=? AND sid=?",
                          (self.namespace,session_id)).fetchone()["n"]
            c.execute("INSERT INTO memory_context VALUES(?,?,?,?,?,?)",
                      (self.namespace,session_id,seq,role,content,time.time()))
            c.execute("""DELETE FROM memory_context WHERE ns=? AND sid=? AND seq NOT IN
              (SELECT seq FROM memory_context WHERE ns=? AND sid=? ORDER BY seq DESC LIMIT 200)""",
              (self.namespace,session_id,self.namespace,session_id))
        return {"stored":True,"sequence":seq}
    def context_get(self,session_id:str,limit:int=50)->dict:
        if not 1<=limit<=200: raise ToolExecutionError("limit must be 1–200.")
        with self.db() as c:
            rows=c.execute("SELECT seq,role,content,created FROM memory_context WHERE ns=? AND sid=? ORDER BY seq DESC LIMIT ?",
                           (self.namespace,session_id,limit)).fetchall()
        items=[dict(x) for x in reversed(rows)]; total=0; kept=[]
        for x in reversed(items):
            if total+len(x["content"])>40000: break
            kept.insert(0,x); total+=len(x["content"])
        return {"entries":kept,"count":len(kept)}
    def context_clear(self,session_id:str)->dict:
        with self.db() as c:
            cur=c.execute("DELETE FROM memory_context WHERE ns=? AND sid=?",(self.namespace,session_id))
        return {"deleted_entries":cur.rowcount}
    def remember(self,session_id:str,content:str,kind:str="episodic",scope:str="user",
                 tags:list[str]|None=None,metadata:dict|None=None,confidence:float=0.8)->dict:
        if not isinstance(content,str) or not content.strip() or len(content)>20000: raise ToolExecutionError("content must be 1–20,000 chars.")
        if kind not in _KINDS or scope not in {"user","session"}: raise ToolExecutionError("Invalid kind/scope.")
        if not isinstance(confidence,(int,float)) or not 0<=confidence<=1: raise ToolExecutionError("confidence must be 0–1.")
        tags=tags or []
        if not isinstance(tags,list) or len(tags)>30 or any(not isinstance(x,str) or not x.strip() or len(x)>64 for x in tags):
            raise ToolExecutionError("Invalid tags.")
        meta=_metadata(metadata or {}); now=time.time(); mid=uuid.uuid4().hex
        vec=self.embedding(content)
        with self.db() as c:
            count=c.execute("SELECT COUNT(*) n FROM memory_items WHERE ns=?",(self.namespace,)).fetchone()["n"]
            if count>=self.max_items: raise ToolExecutionError("Memory capacity reached; consolidate or forget records.")
            c.execute("INSERT INTO memory_items(id,ns,sid,kind,scope,content,tags,metadata,confidence,vector,fingerprint,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (mid,self.namespace,session_id,kind,scope,content,json.dumps(sorted(set(tags))),json.dumps(meta,ensure_ascii=False),
               float(confidence),json.dumps(vec),_fingerprint(content),now,now))
        return {"memory_id":mid,"stored":True,"kind":kind,"scope":scope}
    def recall(self,session_id:str,query:str,kind:str|None=None,scope:str="all",limit:int=10,min_score:float=0.05)->dict:
        if not isinstance(query,str) or not query.strip() or len(query)>4000: raise ToolExecutionError("Invalid query.")
        if kind is not None and kind not in _KINDS: raise ToolExecutionError("Invalid kind.")
        if scope not in {"all","user","session"} or not 1<=limit<=50 or not 0<=min_score<=1:
            raise ToolExecutionError("Invalid recall bounds.")
        where=["ns=?","(scope='user' OR sid=?)"]; args=[self.namespace,session_id]
        if kind: where.append("kind=?"); args.append(kind)
        with self.db() as c:
            rows=c.execute("SELECT * FROM memory_items WHERE "+" AND ".join(where)+" ORDER BY updated DESC LIMIT 5000",args).fetchall()
        if scope=="user": rows=[r for r in rows if r["scope"]=="user"]
        if scope=="session": rows=[r for r in rows if r["scope"]=="session"]
        qt=set(_tokens(query)); qv=self.embedding(query); scored=[]; now=time.time()
        for r in rows:
            lexical=len(qt & set(_tokens(r["content"])))/max(1,len(qt))
            vector=_cos(qv,json.loads(r["vector"]))
            recency=math.exp(-max(0,now-r["updated"])/(365*86400))
            score=.45*lexical+.45*vector+.07*r["confidence"]+.03*recency
            if score>=min_score: scored.append((score,r))
        scored.sort(key=lambda x:(x[0],x[1]["updated"]),reverse=True); output=[]; ids=[]
        for score,r in scored[:limit]:
            ids.append(r["id"]); output.append({"memory_id":r["id"],"kind":r["kind"],"scope":r["scope"],
              "content":r["content"],"tags":json.loads(r["tags"]),"metadata":json.loads(r["metadata"]),
              "confidence":r["confidence"],"score":round(score,5),"created_at":r["created"],"updated_at":r["updated"]})
        if ids:
            with self.db() as c: c.executemany("UPDATE memory_items SET accesses=accesses+1 WHERE ns=? AND id=?",
                                               [(self.namespace,x) for x in ids])
        return {"memories":output,"count":len(output),"retrieval":"hybrid_vector_lexical"}
    def update(self,session_id:str,memory_id:str,content:str|None=None,tags:list[str]|None=None,
               metadata:dict|None=None,confidence:float|None=None)->dict:
        with self.db() as c:
            r=c.execute("SELECT * FROM memory_items WHERE ns=? AND id=? AND (scope='user' OR sid=?)",
                        (self.namespace,memory_id,session_id)).fetchone()
            if r is None: raise ToolExecutionError("Memory not found in active scope.")
            body=content if content is not None else r["content"]
            if not isinstance(body,str) or not body.strip() or len(body)>20000: raise ToolExecutionError("Invalid content.")
            ts=tags if tags is not None else json.loads(r["tags"])
            if not isinstance(ts,list) or len(ts)>30 or any(not isinstance(x,str) or not x.strip() or len(x)>64 for x in ts):
                raise ToolExecutionError("Invalid tags.")
            meta=_metadata(metadata if metadata is not None else json.loads(r["metadata"]))
            conf=float(confidence) if confidence is not None else r["confidence"]
            if not 0<=conf<=1: raise ToolExecutionError("confidence must be 0–1.")
            c.execute("UPDATE memory_items SET content=?,tags=?,metadata=?,confidence=?,vector=?,fingerprint=?,updated=? WHERE ns=? AND id=?",
              (body,json.dumps(sorted(set(ts))),json.dumps(meta,ensure_ascii=False),conf,json.dumps(self.embedding(body)),
               _fingerprint(body),time.time(),self.namespace,memory_id))
        return {"memory_id":memory_id,"updated":True}
    def forget(self,session_id:str,memory_id:str)->dict:
        with self.db() as c:
            cur=c.execute("DELETE FROM memory_items WHERE ns=? AND id=? AND (scope='user' OR sid=?)",
                          (self.namespace,memory_id,session_id))
        return {"memory_id":memory_id,"forgotten":cur.rowcount==1}
    def consolidate(self,session_id:str,kind:str|None=None)->dict:
        where=["ns=?","(scope='user' OR sid=?)"]; args=[self.namespace,session_id]
        if kind:
            if kind not in _KINDS: raise ToolExecutionError("Invalid kind.")
            where.append("kind=?"); args.append(kind)
        removed=0; seen={}
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            rows=c.execute("SELECT * FROM memory_items WHERE "+" AND ".join(where)+" ORDER BY confidence DESC,updated DESC",args).fetchall()
            for r in rows:
                old=seen.get(r["fingerprint"])
                if old is None: seen[r["fingerprint"]]=r; continue
                tags=sorted(set(json.loads(old["tags"])+json.loads(r["tags"])))
                meta=json.loads(old["metadata"])
                for k,v in json.loads(r["metadata"]).items(): meta.setdefault(k,v)
                c.execute("UPDATE memory_items SET tags=?,metadata=?,confidence=?,updated=? WHERE ns=? AND id=?",
                  (json.dumps(tags),json.dumps(meta,ensure_ascii=False),max(old["confidence"],r["confidence"]),time.time(),self.namespace,old["id"]))
                c.execute("DELETE FROM memory_items WHERE ns=? AND id=?",(self.namespace,r["id"])); removed+=1
        return {"duplicates_removed":removed,"remaining_unique":len(seen)}

class MemoryTool:
    def __init__(self,name:str,description:str,schema:dict,capability:str,fn:Callable):
        self.spec=ToolSpec(name=name,description=description,input_schema=schema,
          capabilities=frozenset({capability}),timeout_seconds=15,max_output_chars=30000)
        self.fn=fn
    async def invoke(self,arguments:dict,context:ToolContext):
        try: return await asyncio.wait_for(asyncio.to_thread(self.fn,session_id=context.session_id,**arguments),timeout=14)
        except TimeoutError as exc: raise ToolExecutionError("Memory operation timed out.") from exc
        except ToolExecutionError: raise
        except Exception as exc: raise ToolExecutionError(f"Memory operation failed ({type(exc).__name__}).") from exc

def create_memory_tools(database:str|Path,*,namespace:str,embedder:Callable[[str],list[float]]|None=None,
                        max_items:int=100000)->tuple[MemoryTool,...]:
    store=PersistentMemory(database,namespace=namespace,embedder=embedder,max_items=max_items)
    txt={"type":"string","minLength":1,"maxLength":20000}
    tags={"type":"array","items":{"type":"string","minLength":1,"maxLength":64},"maxItems":30,"uniqueItems":True}
    meta={"type":"object","maxProperties":50}
    return (
      MemoryTool("memory.context_append","Append a role-tagged entry to active session context.",object_schema({"role":{"type":"string","enum":["system","user","assistant","tool"]},"content":txt},["role","content"]),"memory:context:write",store.context_append),
      MemoryTool("memory.context_get","Read recent context from active session.",object_schema({"limit":{"type":"integer","minimum":1,"maximum":200}}),"memory:context:read",store.context_get),
      MemoryTool("memory.context_clear","Delete active session context.",object_schema({}),"memory:context:delete",store.context_clear),
      MemoryTool("memory.remember","Persist episodic, semantic or procedural memory.",object_schema({"content":txt,"kind":{"type":"string","enum":sorted(_KINDS)},"scope":{"type":"string","enum":["user","session"]},"tags":tags,"metadata":meta,"confidence":{"type":"number","minimum":0,"maximum":1}},["content"]),"memory:write",store.remember),
      MemoryTool("memory.recall","Hybrid vector and lexical similarity search over visible memories.",object_schema({"query":{"type":"string","minLength":1,"maxLength":4000},"kind":{"type":"string","enum":sorted(_KINDS)},"scope":{"type":"string","enum":["all","user","session"]},"limit":{"type":"integer","minimum":1,"maximum":50},"min_score":{"type":"number","minimum":0,"maximum":1}},["query"]),"memory:read",store.recall),
      MemoryTool("memory.update","Correct memory content, tags, metadata or confidence.",object_schema({"memory_id":{"type":"string","minLength":1,"maxLength":64},"content":txt,"tags":tags,"metadata":meta,"confidence":{"type":"number","minimum":0,"maximum":1}},["memory_id"]),"memory:write",store.update),
      MemoryTool("memory.forget","Permanently delete a memory within active user/session scope.",object_schema({"memory_id":{"type":"string","minLength":1,"maxLength":64}},["memory_id"]),"memory:delete",store.forget),
      MemoryTool("memory.consolidate","Merge exact duplicate memories and combine tags/metadata.",object_schema({"kind":{"type":"string","enum":sorted(_KINDS)}}),"memory:maintenance",store.consolidate),
    )
