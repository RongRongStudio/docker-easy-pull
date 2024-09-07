import sys
import requests
import urllib3
import gzip
import hashlib
import json
import os
import shutil
import tarfile

urllib3.disable_warnings()


def get_head_auth(kind):
    resp_auth = requests.get(f'{auth_url}?service={reg_service}&scope=repository:{repository}:pull', verify=False)
    access_token = resp_auth.json()['token']
    head_auth = {'Authorization': 'Bearer ' + access_token, 'Accept': kind}
    return head_auth


def progress_bar(u_blob, nb_traits):
    sys.stdout.write('\r' + u_blob[7:19] + ': Downloading [')
    for i in range(0, nb_traits):
        if i == nb_traits - 1:
            sys.stdout.write('>')
        else:
            sys.stdout.write('=')
    for i in range(0, 49 - nb_traits):
        sys.stdout.write(' ')
    sys.stdout.write(']')
    sys.stdout.flush()


cmd = sys.argv[1:]
repo = 'library'
tag = 'latest'
name_split = cmd[1].split('/')
try:
    img, tag = name_split[-1].split(':')
except:
    img = name_split[-1]
# TODO:other docker registry handle
if len(name_split) > 1 and ('.' in name_split[0] or ':' in name_split[0]):
    registry = name_split[0]
    repo = '/'.join(name_split[1:-1])
else:
    registry = 'registry-1.docker.io'
    if len(name_split[:-1]) != 0:
        repo = '/'.join(name_split[:-1])
    else:
        repo = 'library'
repository = f'{repo}/{img}'
resp_registry = requests.get(f'https://{registry}/v2/', verify=False)
auth_url = resp_registry.headers['WWW-Authenticate'].split('"')[1]
reg_service = resp_registry.headers['WWW-Authenticate'].split('"')[3]
# TODO:mediaType optimize
auth_head = get_head_auth('application/vnd.docker.distribution.manifest.list.v2+json')
resp_single = requests.get(f'https://{registry}/v2/{repository}/manifests/{tag}', headers=auth_head, verify=False)
resp_repository_content = resp_single.json()
if cmd[0] == 'show' and len(cmd) == 2:
    if 'manifests' in resp_repository_content:
        print('multiple platforms')
        for i in resp_repository_content['manifests']:
            # TODO:show beautiful
            print(i["platform"]['architecture'])
    else:
        print(f"single platform:{resp_repository_content['architecture']}")
elif cmd[0] == 'pull':
    if len(cmd) == 2:
        if 'manifests' not in resp_repository_content:
            # TODO:mediaType optimize
            arch = resp_repository_content['architecture']
            auth_head = get_head_auth('application/vnd.docker.distribution.manifest.v2+json')
            resp_single = requests.get(f'https://{registry}/v2/{repository}/manifests/{tag}', headers=auth_head, verify=False)
            resp_single_content = resp_single.json()
            layers = resp_single_content['layers']
            config_digest = resp_single_content['config']['digest']
    elif len(cmd) == 3:
        if 'manifests' in resp_repository_content:
            manifests = resp_repository_content['manifests']
            for i in manifests:
                if i['platform']['architecture'] == cmd[2]:
                    # TODO:mediaType optimize
                    arch = cmd[2]
                    auth_head = get_head_auth('application/vnd.oci.image.manifest.v1+json')
                    resp_platform = requests.get(f"https://{registry}/v2/{repository}/manifests/{i['digest']}", headers=auth_head, verify=False)
                    resp_platform_content = resp_platform.json()
                    layers = resp_platform_content['layers']
                    config_digest = resp_platform_content['config']['digest']
                    break
    img_dir = f"tmp_{img}_{tag.replace(':', '@')}_{arch}"
    os.mkdir(img_dir)
    print('Creating image folder: ' + img_dir)
    resp_conf = requests.get(f'https://{registry}/v2/{repository}/blobs/{config_digest}', headers=auth_head,
                             verify=False)
    with open(f'{img_dir}/{config_digest[7:]}.json', 'wb') as f:
        f.write(resp_conf.content)
    content = [{
        'Config': config_digest[7:] + '.json',
        'RepoTags': [],
        'Layers': []
    }]
    # TODO:other docker registry handle
    if len(name_split[:-1]) != 0:
        content[0]['RepoTags'].append('/'.join(name_split[:-1]) + '/' + img + ':' + tag)
    else:
        content[0]['RepoTags'].append(img + ':' + tag)
    empty_json = '{"created":"1970-01-01T00:00:00Z","container_config":{"Hostname":"","Domainname":"","User":"","AttachStdin":false, \
    	"AttachStdout":false,"AttachStderr":false,"Tty":false,"OpenStdin":false, "StdinOnce":false,"Env":null,"Cmd":null,"Image":"", \
    	"Volumes":null,"WorkingDir":"","Entrypoint":null,"OnBuild":null,"Labels":null}}'
    parent_id = ''
    for layer in layers:
        u_blob = layer['digest']
        fake_layer_id = hashlib.sha256((parent_id + '\n' + u_blob + '\n').encode('utf-8')).hexdigest()
        layer_dir = img_dir + '/' + fake_layer_id
        os.mkdir(layer_dir)
        with open(layer_dir + '/VERSION', 'w') as f:
            f.write('1.0')
        sys.stdout.write(u_blob[7:19] + ': Downloading...')
        sys.stdout.flush()
        auth_head = get_head_auth(
            'application/vnd.docker.distribution.manifest.v2+json')
        resp_blob = requests.get(f'https://{registry}/v2/{repository}/blobs/{u_blob}', headers=auth_head,
                                 stream=True, verify=False)
        # TODO: different status_code handel
        unit = int(resp_blob.headers['Content-Length']) / 50
        acc = 0
        nb_traits = 0
        progress_bar(u_blob, nb_traits)
        with open(layer_dir + '/layer_gzip.tar', "wb") as file:
            for chunk in resp_blob.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)
                    acc = acc + 8192
                    if acc > unit:
                        nb_traits = nb_traits + 1
                        progress_bar(u_blob, nb_traits)
                        acc = 0
        sys.stdout.write(f'''\r{u_blob[7:19]}: Extracting...{" " * 50}''')
        sys.stdout.flush()
        with open(layer_dir + '/layer.tar', "wb") as file:
            unzLayer = gzip.open(layer_dir + '/layer_gzip.tar', 'rb')
            shutil.copyfileobj(unzLayer, file)
            unzLayer.close()
        os.remove(layer_dir + '/layer_gzip.tar')
        print(f"\r{u_blob[7:19]}: Pull complete [{resp_blob.headers['Content-Length']}]")
        content[0]['Layers'].append(fake_layer_id + '/layer.tar')
        # TODO:every layer json optimize
        with open(layer_dir + '/json', 'w') as f:
            if layers[-1]['digest'] == layer['digest']:
                # FIXME: json.loads() automatically converts to unicode, thus decoding values whereas Docker doesn't
                json_obj = json.loads(resp_conf.content)
                del json_obj['history']
                # TODO: other docker registry handle
                try:
                    del json_obj['rootfs']
                except:
                    del json_obj['rootfS']
            else:
                json_obj = json.loads(empty_json)
            json_obj['id'] = fake_layer_id
            if parent_id:
                json_obj['parent'] = parent_id
            parent_id = json_obj['id']
            f.write(json.dumps(json_obj))

    with open(img_dir + '/manifest.json', 'w') as f:
        f.write(json.dumps(content))

    if len(name_split[:-1]) != 0:
        content = {'/'.join(name_split[:-1]) + '/' + img: {tag: fake_layer_id}}
    else:
        content = {img: {tag: fake_layer_id}}
    with open(img_dir + '/repositories', 'w') as f:
        f.write(json.dumps(content))
    docker_tar = repo.replace('/', '_') + '_' + img + '_' + arch + '.tar'
    sys.stdout.write("Creating archive...")
    sys.stdout.flush()
    with tarfile.open(docker_tar, "w|") as tar:
        tar.add(img_dir, arcname=os.path.sep)
    with open(docker_tar, 'rb') as f_in, gzip.open(docker_tar + '.gz', 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)
    os.remove(docker_tar)
    shutil.rmtree(img_dir)
    print('\rDocker image pulled: ' + docker_tar)
