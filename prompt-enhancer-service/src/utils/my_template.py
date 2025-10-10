import os

from jinja2 import Environment, BaseLoader, FileSystemLoader

from utils import my_tools


def template_str(template: str, model_data: dict, remove_blank_lines: bool = False) -> str:
    content = Environment(loader=BaseLoader()).from_string(template).render(model_data)
    if remove_blank_lines:
        content = my_tools.remove_blank_lines(content)
    return content


def template_file(template_dir: str, template_file_name: str, model_data: dict, to_dir: str, to_file_name: str = None,
                  search_paths: [] = None):
    template_file_path = f"{template_dir}/{template_file_name}"
    if os.path.exists(template_file_path):
        if not search_paths:
            search_paths = [template_dir, f"{template_dir}/..", f"{template_dir}/../_shared"]
        template = Environment(loader=FileSystemLoader(searchpath=search_paths)).get_template(template_file_name)
        content = my_tools.remove_blank_lines(template.render(model_data))
        if not to_file_name:
            to_file_name = template_file_name.replace(".j2", "")
        my_tools.write_txt_to_file(f"{to_dir}/{to_file_name}", content)
    else:
        my_tools.info(f"{template_file_path} does not exist")
