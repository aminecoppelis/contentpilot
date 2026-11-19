"""Public bilingual legal documents supplied by the publisher."""
import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from markupsafe import Markup, escape

from app.i18n import resolve_locale
from app.templating import templates

router = APIRouter(tags=['Legal'])
DOCUMENTS = Path(__file__).resolve().parents[2] / 'legal'


def document_html(text):
    """Render trusted document text without interpreting embedded HTML."""
    blocks=[]
    # Keep numbered sections readable even when the supplied text lacks gaps.
    text=re.sub(r'(?m)^(\d+\.\s|\d+\.\d+\s)', r'\n\n\1', text)
    for block in re.split(r'\n\s*\n',text.strip()):
        block=block.strip()
        if not block:
            continue
        if re.match(r'^\d+\.\d+\s',block):
            head,*rest=block.split('\n',1);blocks.append('<h3>'+str(escape(head))+'</h3>')
            if rest:blocks.append('<p>'+str(escape(rest[0])).replace('\n','<br>')+'</p>')
        elif re.match(r'^\d+\.\s',block):
            head,*rest=block.split('\n',1);blocks.append('<h2>'+str(escape(head))+'</h2>')
            if rest:blocks.append('<p>'+str(escape(rest[0])).replace('\n','<br>')+'</p>')
        elif all(line.startswith('- ') for line in block.splitlines()):
            blocks.append('<ul>'+''.join('<li>'+str(escape(line[2:]))+'</li>' for line in block.splitlines())+'</ul>')
        else:
            blocks.append('<p>'+str(escape(block)).replace('\n','<br>')+'</p>')
    html='\n'.join(blocks).replace('contact_customer@actifpilot.com','<a href="mailto:contact_customer@actifpilot.com">contact_customer@actifpilot.com</a>')
    return Markup(html)


async def page(request, document):
    locale='fr' if resolve_locale(request)=='fr' else 'en'
    titles={'privacy':{'fr':'Politique de Confidentialité','en':'Privacy Policy'},
            'terms':{'fr':'Conditions Générales d’Utilisation (CGU)','en':'Terms of Use'}}
    return templates.TemplateResponse(request,'legal.html',{
        'legal_locale':locale,'document':document,'legal_title':titles[document][locale],
        'legal_body':document_html((DOCUMENTS/(document+'_'+locale+'.txt')).read_text(encoding='utf-8')),
    })


@router.get('/privacy',response_class=HTMLResponse)
async def privacy(request:Request):
    return await page(request,'privacy')


@router.get('/terms',response_class=HTMLResponse)
async def terms(request:Request):
    return await page(request,'terms')
