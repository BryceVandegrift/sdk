import shutil
import subprocess
import os
import sys
import requests
import yaml
import pystache
import knightos.util as util
from knightos.workspace import Workspace
from knightos.kernels import ensure_kernel
import knightos.commands.install as install

def execute(project_name=None, emulator=None, debugger=None, assembler=None, platform=None, vcs=None, kernel_source=None, compiler=None, template=None, force=None, reinit_missing=None):
    root = os.getcwd()
    exists = setup_root(root, project_name, force)
    ws = Workspace(root)
    site_packages = []
    if exists and not project_name:
        project_name = ws.config.get("name")
        print("Found existing project: " + project_name)
        # Grab project-specific options
        if ws.config.get("-sdk-emulator"):
            emulator=ws.config.get("-sdk-emulator")
        if ws.config.get("-sdk-debugger"):
            emulator=ws.config.get("-sdk-debugger")
        if ws.config.get("-sdk-assembler"):
            emulator=ws.config.get("-sdk-assembler")
        if ws.config.get("-sdk-compiler"):
            compiler=ws.config.get("-sdk-compiler")
        if ws.config.get("-sdk-template"):
            template=ws.config.get("-sdk-template")
        if ws.config.get("-sdk-site-packages"):
            site_packages=ws.config.get("-sdk-site-packages").split(" ")
    if template == "c":
        assembler = "scas" # temporary
    template_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
    try:
        with open(os.path.join(template_dir, template, template + ".yaml")) as f:
            template_yaml = yaml.load(f.read(), Loader=yaml.SafeLoader)
    except OSError as e:
        print("Template '" + template + "' not found. Stopping.")
        exit(1)
    template_vars = {
        'project_name': project_name,
        'assembler': assembler,
        'compiler': compiler,
        'emulator': emulator,
        'debugger': debugger,
        'platform': platform,
        'key': '{:02X}'.format(util.get_key(platform)),
        'upgrade_ext': util.get_upgrade_ext(platform),
        'fat': '{:02X}'.format(util.get_fat(platform)),
        'privileged': '{:02X}'.format(util.get_privileged(platform)),
        'kernel_path': kernel_source
    }
    init(ws, root, exists, site_packages, template_yaml, template_vars, vcs, force, reinit_missing)

def init(ws, root, exists, site_packages, template, template_vars, vcs, force, reinit_missing):
    print("Installing SDK...")
    if template_vars['kernel_path'] == None:
        install_kernel(ws.kroot, template_vars['platform'])
        shutil.move(os.path.join(ws.kroot,
            "kernel-" + template_vars['platform'] + ".rom"),
            os.path.join(root, ".knightos", "kernel.rom"))
    else:
        install_local_kernel(ws, template_vars['platform'], template_vars['kernel_path']);

    print("Installing template...")
    template_dir = os.path.join(os.path.dirname(__file__), "..", "templates", template["name"])
    def _compile_file(input_path, output_path, tvars, mode):
        with open(input_path, mode) as src:
            if os.path.basename(output_path) == ".gitignore" and vcs != "git":
                pass
            if "binary" in i and i["binary"]:
                with open(output_path, "wb") as out:
                    out.write(src.read())
            else:
                with open(output_path, "w") as out:
                    out.write(pystache.render(src.read(), template_vars))

    for i in template["files"]:
        input_path = os.path.join(template_dir, i["template"])
        output_path = os.path.join(ws.root, i["path"])
        if not os.path.exists(output_path):
            if not exists or (exists and i["reinit"]) or reinit_missing:
                mode = "r"
                if "binary" in i and i["binary"]:
                    mode = "rb"
                _compile_file(input_path, output_path, template_vars, mode)

    print("Installing packages...")

    filtered_packages = template["install"]
    to_exclude = ws.config.get("-exclude-template-deps")
    if to_exclude:
        to_exclude = to_exclude.split(" ")
        for package in to_exclude:
            if package in filtered_packages:
                filtered_packages.remove(package)

    install.execute(filtered_packages)
    ws = Workspace(root)
    ws.ensure_packages()

    if shutil.which('git') and vcs == "git":
        if not os.path.exists(os.path.join(root, ".git")):
            print("Initializing new git repository...")
            subprocess.call(["git", "init", root], stdout=open(os.devnull, 'w'), stderr=subprocess.STDOUT)
    elif shutil.which('hg') and vcs == "hg":
        if not os.path.exists(os.path.join(root, ".hg")):
            print("Initializing new hg repository...")
            subprocess.call(["hg", "init", root], stdout=open(os.devnull, 'w'), stderr=subprocess.STDOUT)

    # TODO: Check for software listed in template['requries']

    print("All done! You can use `make help` to find out what to do next.")

def setup_root(root, project_name, force):
    kroot = os.path.join(root, ".knightos")
    if os.path.exists(kroot):
        shutil.rmtree(kroot)
        print("Notice: Rebuilding existing environment")
    os.makedirs(root, mode=0o755, exist_ok=True)
    exists = False
    if len(os.listdir(root)) > 0:
        exists = True
    if not exists and not project_name:
        sys.stderr.write("You must specify a project name for new projects.\n")
        sys.exit(1)
    if exists and not os.path.exists(os.path.join(root, "package.config")):
        if not force:
            sys.stderr.write("This directory is not empty and does not appear to have a KnightOS project, aborting!\n")
            sys.exit(1)
        else:
            sys.stderr.write("Warning: forcibly installing SDK in populated directory\n")
    os.makedirs(kroot, mode=0o755)
    os.makedirs(os.path.join(kroot, "include"), mode=0o755)
    os.makedirs(os.path.join(kroot, "packages"), mode=0o755)
    os.makedirs(os.path.join(kroot, "pkgroot"), mode=0o755)
    return exists

def install_kernel(root, platform):
    path, version = ensure_kernel(platform)
    print(os.path.join(root, os.path.basename(path)))
    print("Installing kernel " + version)
    os.symlink(path, os.path.join(root, os.path.basename(path)))
    with open(os.path.join(root, 'kernel-version'), 'w') as f:
        f.write(version)

def install_local_kernel(ws, platform, local_path):
    print("root: " + ws.root)
    print("platform: " + platform)
    print("path: " + local_path)
    kernel_loc = os.path.join(ws.root, local_path, 'bin', platform, 'kernel.rom')
    os.symlink(kernel_loc, os.path.join(ws.root, ws.kroot, 'kernel.rom'))
