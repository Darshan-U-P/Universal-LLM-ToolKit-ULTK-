from __future__ import annotations
import asyncio, json
from pathlib import Path
import pytest
from ultk.builtins.memory import PersistentMemory, create_memory_tools
from ultk.engine import ToolEngine
from ultk.permissions import AllowListPolicy
from ultk.exceptions import ToolExecutionError

def test_context_is_session_scoped_and_restart_safe(tmp_path:Path):
    db=tmp_path/"memory.sqlite3"; store=PersistentMemory(db,namespace="tenant-a")
    store.context_append("s1","user","hello from session one")
    store.context_append("s2","user","other session")
    again=PersistentMemory(db,namespace="tenant-a")
    assert again.context_get("s1")["entries"][0]["content"]=="hello from session one"
    assert again.context_get("s2")["count"]==1

def test_namespace_isolation_and_memory_lifecycle(tmp_path:Path):
    db=tmp_path/"memory.sqlite3"; a=PersistentMemory(db,namespace="tenant-a")
    b=PersistentMemory(db,namespace="tenant-b")
    item=a.remember("s1","User prefers Python examples.",kind="semantic",tags=["preference"])
    assert a.recall("s2","Python examples")["count"]==1
    assert b.recall("s2","Python examples")["count"]==0
    assert a.update("s2",item["memory_id"],confidence=.95)["updated"]
    assert a.recall("s2","Python examples")["memories"][0]["confidence"]==.95
    assert a.forget("s2",item["memory_id"])["forgotten"]
    assert a.recall("s2","Python examples")["count"]==0

def test_session_scope_isolation(tmp_path:Path):
    s=PersistentMemory(tmp_path/"m.sqlite3",namespace="tenant")
    s.remember("s1","temporary project detail",scope="session")
    assert s.recall("s2","temporary project detail")["count"]==0
    assert s.recall("s1","temporary project detail")["count"]==1

def test_duplicate_consolidation(tmp_path:Path):
    s=PersistentMemory(tmp_path/"m.sqlite3",namespace="tenant")
    s.remember("s","Remember this exact fact.",tags=["one"],metadata={"a":1})
    s.remember("s"," remember THIS exact fact ",tags=["two"],metadata={"b":2})
    assert s.consolidate("s")["duplicates_removed"]==1
    result=s.recall("s","exact fact")["memories"]
    assert len(result)==1 and result[0]["tags"]==["one","two"]
    assert result[0]["metadata"]=={"a":1,"b":2}

def test_host_embedder_used_and_persisted(tmp_path:Path):
    calls=[]
    def embed(text:str)->list[float]:
        calls.append(text); return [1.0]+[0.0]*7
    s=PersistentMemory(tmp_path/"m.sqlite3",namespace="tenant",embedder=embed)
    s.remember("s","semantic memory",kind="semantic")
    assert s.recall("s","related query")["retrieval"]=="hybrid_vector_lexical"
    assert calls

def test_tools_take_session_from_dispatch_context(tmp_path:Path):
    tools=create_memory_tools(tmp_path/"m.sqlite3",namespace="tenant")
    engine=ToolEngine(policy=AllowListPolicy(
      allowed_tools=frozenset({"memory.context_append","memory.context_get"}),
      granted_capabilities=frozenset({"memory:context:write","memory:context:read"})))
    engine.register_tools(tools)
    async def run():
        w=await engine.execute("memory.context_append",{"role":"user","content":"hi"},
          session_id="trusted-session",granted_capabilities=frozenset({"memory:context:write"}))
        r=await engine.execute("memory.context_get",{"limit":10},
          session_id="trusted-session",granted_capabilities=frozenset({"memory:context:read"}))
        return json.loads(w.content),json.loads(r.content)
    w,r=asyncio.run(run())
    assert w["stored"] and r["entries"][0]["content"]=="hi"

def test_bad_namespace_and_values_rejected(tmp_path:Path):
    with pytest.raises(ValueError): PersistentMemory(tmp_path/"m.sqlite3",namespace="../tenant")
    s=PersistentMemory(tmp_path/"m.sqlite3",namespace="tenant")
    with pytest.raises(ToolExecutionError): s.remember("s","bad confidence",confidence=2)
