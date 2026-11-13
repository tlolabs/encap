#!/usr/bin/env python3
"""Package immutable source with the existing native deployment/runtime helpers."""
import argparse, hashlib, importlib.util, json, os, platform, shutil, subprocess, sys, tomllib
from pathlib import Path
from types import SimpleNamespace

def run(*args, **kw):
    return subprocess.run([str(a) for a in args], check=True, **kw)

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

def main():
    p=argparse.ArgumentParser(); p.add_argument('phase',choices=['stage','finish']); p.add_argument('--source',type=Path,required=True); p.add_argument('--target',required=True); p.add_argument('--tag',required=True); p.add_argument('--sha',required=True); p.add_argument('--windows-signing',choices=['unsigned']); a=p.parse_args()
    root=a.source.resolve(); os.chdir(root)
    machine='arm64' if platform.machine().lower() in ('arm64','aarch64') else 'x64'
    host='windows' if sys.platform=='win32' else 'linux' if sys.platform=='linux' else 'unsupported'
    if a.target != f'{host}-{machine}': raise ValueError('Native target mismatch')
    version=tomllib.loads((root/'Cargo.toml').read_text())['workspace']['package']['version']
    if a.tag!='v'+version or subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()!=a.sha: raise ValueError('Tag/version/source mismatch')
    os.environ['ENCAP_RELEASE']='1'
    sys.path.insert(0,str(root/'script'))
    runtime=load(root/'script/ffmpeg_runtime.py','runtime')
    target=host+'-'+('x86_64' if machine=='x64' else machine)
    stage=root/'dist/staging/EnCap'; binary=stage if host=='windows' else stage/'bin'
    suffix='.exe' if host=='windows' else ''
    if a.phase=='stage':
        tools=root/'build/weekly-tools'; tools.mkdir(parents=True,exist_ok=True)
        triple=('aarch64' if machine=='arm64' else 'x86_64')+'-pc-windows-msvc'
        cargo=root/'target'/triple/'release' if host=='windows' else root/'target/release'
        for tool in ['encap-engine','encap-update']+(['encap-portable-update'] if host=='windows' else []): shutil.copy2(cargo/(tool+suffix),tools/(tool+suffix))
        acquired=runtime.provision(target); runtime.stage(target, acquired, tools)
        runtime.finish(target,tools,tools/'ffmpeg-runtime')
        runtime.validate(target,tools,tools/'ffmpeg-runtime',acquired)
        # Deployment logic is trusted workflow control; application inputs remain the tag.
        qt=load(Path(__file__).resolve().parents[2]/'script/build_qt.py','qt'); qt.ROOT=root
        prefix=root/'Qt/6.10.3'/('msvc2022_arm64' if machine=='arm64' else 'msvc2022_64') if host=='windows' else None
        qt.build(SimpleNamespace(rid=('win' if host=='windows' else 'linux')+'-'+machine,tools=tools,qt_prefix=prefix,smoke_only=True,run=False))
        return
    out=root/'dist/weekly'; out.mkdir(parents=True,exist_ok=True)
    if host=='windows':
        if a.windows_signing != 'unsigned': raise ValueError('Weekly Windows packaging requires explicit unsigned mode')
        verifier=Path(__file__).resolve().with_name('verify_weekly_windows.ps1')
        verify_args=['pwsh','-NoProfile','-File',verifier,'-Version',version]
        run(*verify_args,'-Folder',stage)
        runtime.finish(target,binary,binary/'ffmpeg-runtime')
        names=[str(f.relative_to(stage)) for f in stage.rglob('*') if f.is_file()]
        (stage/'portable-package-files.json').write_text(json.dumps(names))
        label='-unsigned'
        package=Path(shutil.make_archive(str(out/f'EnCap-{version}-{a.target}{label}'),'zip',stage))
        extracted=root/'build/weekly-final'; shutil.unpack_archive(package,extracted); binary=extracted
        run(*verify_args,'-Folder',binary)
    else:
        (root/'dist/release').mkdir(parents=True,exist_ok=True)
        run('bash',root/'script/package_appimage.sh','aarch64' if machine=='arm64' else 'x86_64',stage,version)
        package=out/f'EnCap-{version}-{a.target}.AppImage'; shutil.copy2(root/'dist/release'/package.name,package)
        extracted=root/'build/weekly-final'; extracted.mkdir(parents=True,exist_ok=True)
        run(package,'--appimage-extract',cwd=extracted,stdout=subprocess.DEVNULL); binary=extracted/'squashfs-root/usr/bin'
    runtime.validate(target,binary,binary/'ffmpeg-runtime',None)
    env=os.environ.copy()
    for key in list(env):
        if key.startswith('ENCAP_TEST_') or key in ('QT_PLUGIN_PATH','ENCAP_FFMPEG','ENCAP_FFPROBE'): env.pop(key)
    env['ENCAP_RECOVERY_PATH']=str(root/'build/weekly-final/recovery.json')
    response=json.loads(subprocess.check_output([str(binary/('encap-engine'+suffix)),'startup'],env=env,text=True,timeout=30))
    if not {'providers','presets','recovery'} <= response.keys(): raise ValueError('Engine startup failed')
    run(binary/('encap-engine'+suffix),'validate-tools',env=env,timeout=60)
    app=binary/('EnCap'+suffix) if host=='windows' else extracted/'squashfs-root/AppRun'
    command=[sys.executable,str(root/'script/test_native_startup.py'),str(app)]
    if host=='linux': command=['xvfb-run','-a','dbus-run-session','--']+command
    run(*command,env=env,timeout=90)
    sha=hashlib.sha256(package.read_bytes()).hexdigest()
    (out/(package.name+'.sha256')).write_text(sha+'  '+package.name+'\n')
    (out/'verification.json').write_text(json.dumps(dict(tag=a.tag,sha=a.sha,target=a.target,package=package.name,sha256=sha,status='passed',authenticode=a.windows_signing if host=='windows' else 'not-applicable',scope='native final-package startup, runtime integrity and dependency smoke; not full regression, publisher signing or authenticated updater qualification'))+'\n')
if __name__=='__main__': main()
