import gzip
import hashlib
import json
from pathlib import Path
import uma_asset_explorer as engine
from game_location import settings_path

SCHEMA=2


def encode_probe(probe):
    signature=probe.signature
    return [([signature.label,signature.magic.hex(),signature.category,signature.extension] if signature else None),
            probe.signature_offset,probe.key_name,probe.key.hex() if probe.key else None,
            probe.key_start,probe.raw,probe.confidence]


def decode_probe(row):
    signature=engine.Signature(row[0][0],bytes.fromhex(row[0][1]),row[0][2],row[0][3]) if row[0] else None
    return engine.ProbeResult(signature,row[1],row[2],bytes.fromhex(row[3]) if row[3] else None,row[4],row[5],row[6])


def fingerprint(folder):
    digest=hashlib.sha256(str(SCHEMA).encode())
    paths=sorted(p for p in folder.rglob('*') if p.is_file())
    exe=engine.locate_game_exe(folder)
    if exe:
        paths.append(exe)
    for path in paths:
        stat=path.stat()
        digest.update(f'{path}|{stat.st_size}|{stat.st_mtime_ns}\n'.encode('utf-8'))
    return digest.hexdigest()


def scan_cached(folder,progress=None,force=False):
    folder=Path(folder).resolve()
    key=hashlib.sha256(str(folder).casefold().encode()).hexdigest()[:24]
    target=settings_path().parent/'catalogs'/f'{key}.json.gz'
    stamp=fingerprint(folder)
    try:
        if force:
            raise ValueError('Refresh requested')
        with gzip.open(target,'rt',encoding='utf-8') as stream:
            text=stream.read(64*1024*1024+1)
        if len(text)>64*1024*1024:
            raise ValueError('Catalog too large')
        cache=json.loads(text)
        if cache['schema']!=SCHEMA or cache['fingerprint']!=stamp:
            raise ValueError('Stale catalog')
        sources=[(folder/name,decode_probe(probe)) for name,probe in cache['sources']]
        items=[]
        for source,size,offset,logical,embedded,depth,probe in cache['items']:
            path,source_probe=sources[source]
            items.append(engine.AssetItem(path,folder,size,decode_probe(probe),source_probe,offset,logical,embedded,depth))
        return items,len(sources),True
    except (OSError,ValueError,KeyError,IndexError,TypeError,EOFError):
        pass
    items,count=engine.scan_folder(folder,progress)
    try:
        sources=[]
        source_ids={}
        rows=[]
        for item in items:
            if item.source_path not in source_ids:
                source_ids[item.source_path]=len(sources)
                sources.append([str(item.source_path.relative_to(folder)),encode_probe(item.source_probe)])
            rows.append([source_ids[item.source_path],item.size,item.source_offset,item.logical_path,item.embedded,item.depth,encode_probe(item.probe)])
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_suffix('.tmp')
        with gzip.open(temporary,'wt',encoding='utf-8',compresslevel=3) as stream:
            json.dump({'schema':SCHEMA,'fingerprint':stamp,'sources':sources,'items':rows},stream,ensure_ascii=False,separators=(',',':'))
        temporary.replace(target)
    except (OSError,ValueError):
        pass
    return items,count,False
