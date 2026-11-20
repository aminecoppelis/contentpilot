from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from app.templating import templates

router=APIRouter(tags=['Public pages'])


def render_page(request,section):
    return templates.TemplateResponse(request,'public_page.html',{'public_section':section})


@router.get('/',response_class=HTMLResponse)
async def home(request:Request):return render_page(request,'home')


@router.get('/offers',response_class=HTMLResponse)
async def offers(request:Request):return render_page(request,'offers')


@router.get('/how-it-works',response_class=HTMLResponse)
async def how(request:Request):return render_page(request,'how')


@router.get('/gdpr',response_class=HTMLResponse)
async def security(request:Request):return render_page(request,'security')


@router.get('/pricing',response_class=HTMLResponse)
async def pricing(request:Request):return render_page(request,'pricing')


@router.get('/contact',response_class=HTMLResponse)
async def contact(request:Request):return render_page(request,'contact')
