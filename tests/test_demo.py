import os, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_demo_health_and_write_denial(tmp_path):
    code="""import os
os.environ['FURCOLOR_MODE']='demo'
os.environ['FURCOLOR_DATA_DIR']=r'%s'
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as c:
    h=c.get('/api/health');assert h.status_code==200 and h.json()['uploads'] is False
    assert h.json()['subject_intelligence']=={'available':False,'model':'disabled'}
    assert c.get('/api/projects/123/subjects').json()=={'version':1,'ready':False,'images':{},'clusters':[]}
    p=c.post('/api/projects',json={'name':'x','source_dir':'C:/tmp'});assert p.status_code==400
    assert c.get('/api/projects').json()==[]
""" % str(tmp_path).replace('\\','\\\\')
    result=subprocess.run([sys.executable,"-c",code],cwd=ROOT,text=True,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr
