import json
from pathlib import Path
import uma_asset_explorer as engine


def export_asset(item,path,mode):
    destination=Path(path)
    if mode=='json':
        metadata={'name':Path(item.relative).name,'internal_path':item.relative,
                  'source':str(item.source_path),'offset':item.source_offset,
                  'size_bytes':item.size,'format':item.format_label,
                  'category':item.category,'classification_reason':item.category_reason}
        destination.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        return
    data=engine.decoded_payload(item)
    if data is None:
        raise ValueError('Arquivo inacessível ou maior que 128 MB.')
    if mode=='raw':
        destination.write_bytes(data)
        return
    image,_=engine.decode_visual(item,data)
    if image is None:
        raise ValueError('Este arquivo não possui uma imagem exportável.')
    if mode=='crop':
        bounds=image.getchannel('A').getbbox()
        if bounds:
            image=image.crop(bounds)
    if mode in {'png','crop'}:
        image.save(destination,'PNG')
    elif mode=='webp':
        image.save(destination,'WEBP',lossless=True,method=4,exact=True)
    elif mode=='jpeg':
        background=engine.Image.new('RGBA',image.size,'white')
        background.alpha_composite(image)
        background.convert('RGB').save(destination,'JPEG',quality=95,subsampling=0)
    else:
        raise ValueError('Formato de exportação desconhecido.')
