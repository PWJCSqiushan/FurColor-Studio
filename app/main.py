from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from . import __version__, db, services, settings
from .local_tools import pick
from .security import public_project
ROOT=Path(__file__).resolve().parent.parent
app=FastAPI(title="FurColor Studio",version=__version__,docs_url=None if settings.DEMO else "/api/docs",redoc_url=None)
app.mount("/static",StaticFiles(directory=ROOT/"static"),name="static");templates=Jinja2Templates(directory=ROOT/"templates")
@app.on_event("startup")
def startup():db.init()
@app.get("/",response_class=HTMLResponse)
def index(request:Request):return templates.TemplateResponse(request,"index.html",{"demo":settings.DEMO,"local_token":settings.LOCAL_TOKEN})
@app.get("/api/health")
def health():return {"ok":True,"mode":settings.MODE,"version":__version__,"uploads":False,"port":settings.PORT}
@app.post("/api/local/pick/{kind}")
def local_pick(kind:str,request:Request):
    if request.headers.get("X-FurColor-Local")!=settings.LOCAL_TOKEN:raise HTTPException(403,"本地令牌无效")
    if kind not in {"directory","watermark","manifest"}:raise HTTPException(400,"未知选择器类型")
    try:return {"path":pick(kind)}
    except Exception as exc:raise HTTPException(400,str(exc)) from exc
@app.get("/api/projects")
def projects():return [] if settings.DEMO else [public_project(x) for x in db.rows("SELECT * FROM projects ORDER BY id DESC")]
class ProjectIn(BaseModel):
    name:str=Field(min_length=1,max_length=120);source_dir:str="";edited_dir:str="";analysis_dir:str="";output_dir:str="";watermark_path:str="";manifest_path:str="";selection_mode:str="negative"
class DeliveryIn(BaseModel):
    acknowledgements:list[str];name:str=Field(default="delivery",pattern=r"^[\w.-]{1,80}$");make_zip:bool=True
@app.post("/api/projects")
def project_create(payload:ProjectIn):
    try:return {"id":services.create_project(payload.model_dump())}
    except Exception as exc:raise HTTPException(400,str(exc)) from exc
@app.get("/api/projects/{project_id}/photos")
def photos(project_id:int):return [] if settings.DEMO else db.rows("SELECT id,project_id,stem,selection FROM photos WHERE project_id=? ORDER BY stem",(project_id,))
@app.post("/api/projects/{project_id}/scan")
def scan(project_id:int):
    try:return {"count":services.scan(project_id)}
    except Exception as exc:raise HTTPException(400,str(exc)) from exc
@app.post("/api/projects/{project_id}/selection/{stem}/{value}")
def select(project_id:int,stem:str,value:str):
    try:services.set_selection(project_id,stem,value);return {"ok":True}
    except Exception as exc:raise HTTPException(400,str(exc)) from exc
@app.get("/api/projects/{project_id}/thumb/{stem}")
def thumb(project_id:int,stem:str):
    try:return FileResponse(services.thumbnail(project_id,stem),media_type="image/jpeg")
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc
    except Exception as exc:raise HTTPException(400,str(exc)) from exc
@app.post("/api/projects/{project_id}/jobs/{kind}")
def job(project_id:int,kind:str):
    try:return {"job_id":services.start_job(project_id,kind)}
    except Exception as exc:raise HTTPException(400,str(exc)) from exc
@app.get("/api/projects/{project_id}/jobs")
def jobs(project_id:int):return [] if settings.DEMO else db.rows("SELECT * FROM jobs WHERE project_id=? ORDER BY id DESC",(project_id,))
@app.post("/api/projects/{project_id}/deliver")
def delivery(project_id:int,payload:DeliveryIn):
    try:return services.deliver(project_id,payload.acknowledgements,payload.name,payload.make_zip)
    except Exception as exc:raise HTTPException(400,str(exc)) from exc
