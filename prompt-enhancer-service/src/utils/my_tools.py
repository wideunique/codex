import base64
import copy
import hashlib
import logging
import os
import shutil
import string
import subprocess
import sys
from collections.abc import Mapping
from logging import handlers

from utils import das_config

default_log_config = {
    "handlers": [{
        "level": "debug",
        "name": "Stderr",
        "format": '[%(levelname)s]:%(message)s'
    }]
}


def init_log(log_config: dict = None):
    support_handlers = [default_log_config['handlers'][0]['name'], 'RotatingFile']

    if not log_config:
        log_config = default_log_config

    handler_configs = das_config.get_array_value(log_config, "handlers", default_log_config['handlers'])
    log_handlers = {}
    for handler_config in handler_configs:
        name = das_config.get_str_value(handler_config, "name", default_log_config['handlers'][0]['name'])
        if name in log_handlers:
            continue
        if name not in support_handlers:
            show_error_and_exit(f"Not support log handler name:{name}")
        log_format = das_config.get_str_value(handler_config, "format", default_log_config['handlers'][0]['format'])
        if name == "RotatingFile":

            log_file = das_config.get_str_value(handler_config, "filename",
                                                "logs/service.log")
            if not log_file.startswith("/"):
                log_file = das_config.get_work_path(log_file)
            log_dir = os.path.dirname(log_file)
            if not os.path.isdir(log_dir):
                mk_dir(log_dir)
            info(f"save log to dir:{log_dir}")
            log_handler = handlers.RotatingFileHandler(filename=log_file,
                                                       maxBytes=das_config.get_int_value(handler_config, "maxBytes",
                                                                                         100 * 1024 * 1024),
                                                       backupCount=das_config.get_int_value(handler_config,
                                                                                            "backupCount",
                                                                                            5))
        else:
            log_handler = logging.StreamHandler(sys.stderr)
        log_handlers[name] = log_handler
        log_handler.setFormatter(logging.Formatter(log_format))
        level_str = das_config.get_str_value(handler_config, "level")
        if not level_str:
            level_str = das_config.get_str_value(log_config, "level", default_log_config['handlers'][0]['level'])
        log_level = _get_log_level(level_str)
        log_handler.setLevel(level=log_level)

    logging.basicConfig(
        force=True, handlers=log_handlers.values())


def _get_log_level(level_str):
    if level_str.upper() == 'CRITICAL':
        log_level = logging.CRITICAL
    elif level_str.upper() == 'FATAL':
        log_level = logging.FATAL
    elif level_str.upper() == 'ERROR':
        log_level = logging.ERROR
    elif level_str.upper() == 'WARNING':
        log_level = logging.WARNING
    elif level_str.upper() == 'WARN':
        log_level = logging.WARN
    elif level_str.upper() == 'INFO':
        log_level = logging.INFO
    elif level_str.upper() == 'DEBUG':
        log_level = logging.DEBUG
    elif level_str.upper() == 'NOTSET':
        log_level = logging.NOTSET
    else:
        log_level = logging.INFO
    return log_level


if not logging.root.handlers or len(logging.root.handlers) == 0:
    default_handler_config = default_log_config['handlers'][0]
    logging.basicConfig(format=default_handler_config['format'], level=_get_log_level(default_handler_config['level']))


class This(sys.__class__):  # sys.__class__ is <class 'module'>
    _das_is_debug = True

    @property
    def das_is_debug(self):  # do the property things in this class
        return self._das_is_debug

    @das_is_debug.setter
    def das_is_debug(self, value):  # setter is also OK
        self._das_is_debug = value
        if value:
            log_level_str = "DEBUG"
        else:
            log_level_str = "INFO"

        log_config = copy.deepcopy(default_log_config)
        log_config['handlers'][0]['level'] = log_level_str
        init_log(log_config)


sys.modules[__name__].__class__ = This  # change module class into This


def byte2string(bstr: bytes):
    str_obj = None
    if bstr:
        str_obj = str(bstr, encoding="utf-8")
    return str_obj


def parse_env_string(env_str: str):
    return string.Template(env_str).substitute(os.environ)


def run_shell(cmd_str: str, verbose: bool = True, live: bool = True, encoding="UTF-8", work_dir_path: str = None) -> (
        int, str):
    if verbose:
        debug(f">>>Run cmd:{cmd_str}")
    if live:
        process = subprocess.Popen(cmd_str, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT,
                                   encoding=encoding, cwd=work_dir_path)
        output_str = ''
        while process.poll() is None:
            line = process.stdout.readline()
            line = line.strip()
            if line:
                if verbose:
                    debug(f"{line}")
                output_str += line + "\n"
    else:
        process = subprocess.run(cmd_str, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 shell=True,
                                 encoding=encoding, cwd=work_dir_path)
        output_str = process.stdout
        if verbose:
            debug(f"output_str:{output_str}")
    if verbose:
        debug(f"---Rtn Code:{process.returncode}")
    return process.returncode, output_str


def get_user_home_path():
    return os.environ['HOME']


def get_user_name():
    import getpass
    return getpass.getuser()


def get_real_file_path(origin_path: str) -> str:
    if origin_path.startswith("~/"):
        to_path = get_user_home_path() + "/" + origin_path[2:]
    else:
        to_path = origin_path
    return to_path


def read_txt_from_file(path: str, encoding="UTF-8") -> str:
    dir_path, file_name = split_dir_path_and_file_name(path)
    real_path = f"{dir_path}/{file_name}"
    if not os.path.exists(dir_path):
        return ""
    if not os.path.exists(real_path):
        return ""
    debug(f"real_path:{real_path}")
    with open(file=real_path, mode="r", encoding=encoding) as txtfile:
        return txtfile.read()


def read_lines_from_file(path: str, encoding="UTF-8") -> []:
    dir_path, file_name = split_dir_path_and_file_name(path)
    real_path = f"{dir_path}/{file_name}"
    if not os.path.exists(real_path):
        return []
    with open(file=real_path, mode="r", encoding=encoding) as txtfile:
        lines = [line.rstrip('\n') for line in txtfile.readlines()]
        return lines


def write_lines_to_file(path: str, lines: [] = None, encoding="UTF-8", separator='\n') -> str:
    if not lines:
        lines = []
    return write_txt_to_file(path, separator.join(lines), encoding)


def write_txt_to_file(path: str, content: str, encoding="UTF-8") -> str:
    dir_path, file_name = split_dir_path_and_file_name(path)
    real_path = f"{dir_path}/{file_name}"
    try:
        mk_dir(dir_path)
    except Exception as e:
        error(f"Error:{e}", True)
    debug("write_txt_to_file:" + path)
    with open(file=real_path, mode="w", encoding=encoding) as txtfile:
        txtfile.write(content)
    return real_path


def download_file(path: str, url: str, proxies: Mapping = None, headers: Mapping = None) -> str:
    real_path = get_real_file_path(path)
    dir_path = os.path.dirname(real_path)
    mk_dir(dir_path)
    debug(f"download to {path} ,url:{url}")
    import requests
    r = requests.get(url=url, allow_redirects=True, proxies=proxies, headers=headers)
    with open(file=real_path, mode="wb") as down_file:
        down_file.write(r.content)
    return real_path


def get_seconds(time_str: str) -> int:
    time_str = time_str.replace(' ', '').replace('\t', '').replace('\n', '')
    sec = -1
    if '小时' not in time_str and '分钟' not in time_str:
        sec = -1
    elif '分钟' not in time_str:
        sec = int(time_str.replace('小时', '').strip()) * 3600
    elif '小时' not in time_str:
        sec = int(time_str.replace('分钟', '').strip()) * 60
    else:
        sec = int(time_str[0:time_str.index('小时')].strip()) * 3600 + int(
            time_str[time_str.index('小时') + len('小时'):time_str.index('分钟')].strip()) * 60
    # print(time_str+"->"+str(sec))
    return sec


def only_contain_files(file_info: dict):
    for dir_path in file_info:
        for file in (set(get_file_list(dir_path)) - set(file_info[dir_path])):
            rm_file(dir_path + "/" + file)


def get_file_list(dir_path):
    try:
        file_list = []
        for file_name in os.listdir(dir_path):
            if os.path.isfile(f"{dir_path}/{file_name}"):
                file_list.append(file_name)
        return file_list
    except Exception as e:
        if is_debug():
            error(f"Exception: {e}", exc_info=True)


def is_same_txt_file_content(file_path: str, content: str) -> bool:
    if os.path.exists(file_path):
        text = str(content)
        file_content = read_txt_from_file(file_path)
        return file_content == text
    return False


def split_dir_path_and_file_name(file_full_path) -> (str, str):
    real_path = get_real_file_path(file_full_path)
    dir_path = os.path.dirname(real_path)
    file_name = os.path.basename(real_path)
    return dir_path, file_name


def collect_dir_and_name(file_info: dict, dir: str, name: str):
    dir_path, file_name = split_dir_path_and_file_name(f"{dir}/{name}")
    if dir_path not in file_info:
        file_names = []
        file_info[dir_path] = file_names
    else:
        file_names = file_info[dir_path]
    file_names.append(file_name)


def write_file_if_changed(file_path: str, content: str):
    compare_file_content_status = is_same_txt_file_content(
        file_path, content)
    if compare_file_content_status:
        debug("No change of file:" + file_path)
        return False
    else:
        write_txt_to_file(file_path, content)
        return True


def get_rsync_to_server_cmd(server_info: dict, local_path: str, remote_path: str, delete: bool = False,
                            ignore_files: [] = None) -> str:
    server_user = server_info['user']
    server_host = server_info['host']
    if ignore_files:
        exclude_files_str = ' '.join(
            list(map(lambda x: "--exclude='%s'" % x, ignore_files)))
    else:
        exclude_files_str = ''
    arg_delete = ''
    if delete:
        arg_delete = '--delete'
    cmd_server = f"rsync -e 'ssh -o StrictHostKeyChecking=no' -av  {exclude_files_str} {arg_delete}  {local_path} {server_user}@{server_host}:{remote_path}"
    return cmd_server


def rsync_to_server(server_info: dict, local_path: str, remote_path: str, delete: bool = False,
                    ignore_files: [] = None) -> (
        int, str):
    return run_shell(get_rsync_to_server_cmd(server_info, local_path, remote_path, delete, ignore_files))


def get_scp_to_server_cmd(server_info: dict, local_path: str, remote_path: str) -> str:
    server_user = server_info['user']
    server_host = server_info['host']
    cmd_server = f'scp -r {local_path} {server_user}@{server_host}:{remote_path}'
    return cmd_server


def scp_to_server(server_info: dict, local_path: str, remote_path: str) -> (int, str):
    return run_shell(get_scp_to_server_cmd(server_info, local_path, remote_path))


def scp_from_server(server_info: dict, remote_path: str, local_path: str) -> (int, str):
    server_user = server_info['user']
    server_host = server_info['host']
    cmd_server = f'scp -r {server_user}@{server_host}:{remote_path} {local_path} '
    return run_shell(cmd_server)


def get_run_shell_on_server_cmd(server_info: dict, cmd_str: str) -> str:
    server_user = server_info['user']

    if 'ip' in server_info:
        server_host = server_info['ip']
    else:
        server_host = server_info['host']

    cmd_server = f'ssh -o StrictHostKeyChecking=no {server_user}@{server_host}  {cmd_str}'
    return cmd_server


def run_shell_on_server(server_info: dict, cmd_str: str, live: bool = True, encoding="UTF-8") -> (int, str):
    if not server_info or 'user' not in server_info or (
            'ip' not in server_info and 'host' not in server_info):
        return run_shell(cmd_str=cmd_str, live=live, encoding=encoding)
    return run_shell(get_run_shell_on_server_cmd(server_info, cmd_str), live=live, encoding=encoding)


def is_debug():
    return getattr(sys.modules[__name__], 'das_is_debug') or os.getenv("DAS_IS_DEBUG") == "true"


def rm_dir(dir_path: str):
    if os.path.exists(dir_path):
        debug(f"rm_dir:{dir_path}")
        shutil.rmtree(dir_path)


def rm_file(file_path: str):
    if os.path.exists(file_path):
        debug(f"rm_file:{file_path}")
        os.remove(file_path)


def make_archive(base_name, format, root_dir: str):
    shutil.make_archive(base_name, format, root_dir)
    debug(f"Make archive from dir:{root_dir} to {base_name} by format: {format}")


def copy_dir(from_dir_path: str, to_dir_path: str):
    run_shell(f'mkdir -p "{to_dir_path}" && cp -rf "{from_dir_path}"/* "{to_dir_path}"')


def copy_file(from_file_path: str, to_file_path: str):
    mk_dir(os.path.dirname(to_file_path))
    import shutil
    shutil.copy(from_file_path, to_file_path)
    debug(f"copy_file from: {from_file_path} to {to_file_path} ")


def mk_dir(dir_path: str):
    if not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)
        debug(f"mk_dir:{dir_path}")


def sync_file_paths(paths: [], from_base_path: str, to_base_path: str):
    for copy_path_info in paths:
        from_path = copy_path_info['from_path']
        # 是否删除目标路径
        is_delete = das_config.get_bool_value(from_path, "is_delete", False)
        to_path = das_config.get_str_value(copy_path_info, "to_path", from_path)
        if is_delete:
            if os.path.isfile(to_path):
                rm_file(to_path)
            elif os.path.isdir(to_path):
                rm_dir(to_path)
            else:
                debug(f"The to_path:{to_path} is not exist, so there is no need to remove it.")
        else:
            full_from_path = f"{from_base_path}/{from_path}"
            full_to_path = f"{to_base_path}/{to_path}"
            if os.path.isfile(full_from_path):
                copy_file(full_from_path, full_to_path)
            else:
                copy_dir(full_from_path, full_to_path)


def debug(msg):
    if is_debug():
        logging.debug(f"{msg}")


def info(msg):
    logging.info(f"{msg}")


def error(msg, exc_info: bool = False):
    logging.error(f"{msg}", exc_info=exc_info)


def show_error_and_exit(err_msg: str, exc_info=False):
    err_msg_rerun = "Please fix it and rerun this script!!!"
    error(msg=f"{err_msg} {err_msg_rerun}", exc_info=exc_info)
    exit(1)


def show_message_and_exit(msg: str):
    msg_exit = "Script exit!!!"
    error(f"{msg} {msg_exit}")
    exit(0)


def is_in_filters(filters_str: str, value: str) -> bool:
    if not filters_str:
        return True
    return value in filters_str.split(",")


def is_ignore_by_filters(filters_str: str, value: str) -> bool:
    return not is_in_filters(filters_str, value)


def base64_decode_to_str(s) -> str:
    return base64_decode_to_bytes(s).decode('utf-8')


def base64_decode_to_bytes(s):
    return base64.b64decode(s)


def base64_encode(s) -> str:
    if isinstance(s, str):
        s = s.encode('utf-8')
    return base64.b64encode(s).decode("utf-8")


def do_action_with_retry(func_action, max_count: int = 3):
    n = 0
    while n < max_count:
        try:
            n = n + 1
            return func_action()
        except Exception as e:
            logging.error(f"tries:{n},Exception: {e},return empty")
    return None


def md5_file(file_path) -> str:
    if not os.path.isfile(file_path):
        debug(f"{file_path} is not a file")
        return ""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def md5_str(text: str):
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def parse_url_parameters_to_dict(url: str, multi_value=False):
    import urllib.parse
    query = urllib.parse.urlsplit(url).query
    params = urllib.parse.parse_qs(query)
    if not multi_value:
        params = {k: v[0] for k, v in params.items()}

    return params


def get_all_leaf_dirs(base_dir: str) -> set:
    real_path = get_real_file_path(base_dir)
    if not real_path.endswith("/"):
        real_path = real_path + "/"
    leaf_dirs = set()
    for path_info in os.walk(real_path):
        if len(path_info[1]) == 0 and len(path_info[2]) > 0:
            full_path = path_info[0]
            sub_path = full_path.replace(real_path, "")
            leaf_dirs.add(sub_path)
    return leaf_dirs


def get_parent_dir(file_path: str):
    return os.path.dirname(file_path)


def get_file_name(file_path: str):
    return os.path.basename(file_path)


def get_file_ext(file_path: str):
    return os.path.splitext(file_path)[-1][1:]


def remove_blank_lines(text: str) -> str:
    to_lines = []
    for line in text.split("\n"):
        if len(line.strip()) != 0:
            to_lines.append(line)
    return "\n".join(to_lines)
