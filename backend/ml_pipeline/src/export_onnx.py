"""
Export pretrained WLASL checkpoints from Hugging Face to ONNX.
"""

from __future__ import annotations

import importlib
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable


REPO_ID = "sharonn18/tgcn-wlasl"
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
WEB_PUBLIC_DIR = REPO_ROOT / "web" / "public"
VENDOR_DIR = SCRIPT_DIR / "_hf_tgcn"
ARTIFACT_DIR = SCRIPT_DIR / "_onnx_artifacts"
REQUIRED_PACKAGES = {
    "torch": "torch",
    "torchvision": "torchvision",
    "numpy": "numpy",
    "huggingface_hub": "huggingface_hub",
    "onnx": "onnx",
}
MODEL_SPECS = {
    "asl100": 100,
    "asl2000": 2000,
}
LABEL_EXTENSIONS = {".json", ".txt", ".csv"}


def ensure_dependencies() -> None:
    missing = [
        package_name
        for module_name, package_name in REQUIRED_PACKAGES.items()
        if importlib.util.find_spec(module_name) is None
    ]
    if not missing:
        return

    print(f"Installing missing packages: {', '.join(missing)}")
    subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])


def prepare_dirs() -> None:
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    WEB_PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    init_file = VENDOR_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text("", encoding="utf-8")


def download_repo_file(hf_hub_download, filename: str, local_dir: Path) -> Path:
    path = hf_hub_download(repo_id=REPO_ID, filename=filename, local_dir=str(local_dir))
    return Path(path)


def import_vendor_modules():
    sys.path.insert(0, str(VENDOR_DIR))
    importlib.invalidate_caches()

    tgcn_module = importlib.import_module("tgcn_model")
    configs_module = importlib.import_module("configs")
    return tgcn_module.GCN_muti_att, configs_module.Config


def normalize_state_dict(state_dict):
    if not isinstance(state_dict, dict) or not state_dict:
        return state_dict

    prefixes = ("module.", "model.")
    keys = list(state_dict.keys())
    for prefix in prefixes:
        if all(key.startswith(prefix) for key in keys):
            return {key[len(prefix):]: value for key, value in state_dict.items()}
    return state_dict


def replace_file(src: Path, dst: Path) -> None:
    if dst.exists():
        dst.unlink()
    shutil.move(str(src), str(dst))


def copy_file(src: Path, dst: Path) -> None:
    if dst.exists():
        dst.unlink()
    shutil.copy2(src, dst)


def select_label_files(repo_files: Iterable[str]) -> list[str]:
    matches: list[str] = []
    for repo_file in repo_files:
        path = Path(repo_file)
        name = path.name.lower()
        if path.suffix.lower() not in LABEL_EXTENSIONS:
            continue
        if name == "labels.json":
            matches.append(repo_file)
            continue
        if "classes" in name or name.startswith("class_") or name.startswith("class-"):
            matches.append(repo_file)
            continue
        if name.startswith("class.") or name.startswith("classes."):
            matches.append(repo_file)
            continue
    return sorted(set(matches))


def destination_name(repo_file: str) -> str:
    path = Path(repo_file)
    if len(path.parts) == 1:
        return path.name
    stem = "_".join(path.parts[:-1] + (path.stem,))
    return f"{stem}{path.suffix}"


def export_model(torch, hf_hub_download, Config, GCN_muti_att, model_size: str, num_classes: int) -> Path:
    checkpoint_path = download_repo_file(
        hf_hub_download,
        f"checkpoints/{model_size}/pytorch_model.bin",
        ARTIFACT_DIR / "checkpoints" / model_size,
    )
    config_path = download_repo_file(
        hf_hub_download,
        f"checkpoints/{model_size}/config.ini",
        ARTIFACT_DIR / "checkpoints" / model_size,
    )

    config = Config(str(config_path))
    model = GCN_muti_att(
        input_feature=config.num_samples * 2,
        hidden_feature=config.hidden_size,
        num_class=num_classes,
        p_dropout=config.drop_p,
        num_stage=config.num_stages,
    )

    checkpoint = torch.load(str(checkpoint_path), map_location="cpu")
    state_dict = checkpoint.get("state_dict", checkpoint) if isinstance(checkpoint, dict) else checkpoint
    state_dict = normalize_state_dict(state_dict)
    load_result = model.load_state_dict(state_dict, strict=False)

    if load_result.missing_keys:
        print(f"{model_size}: missing keys during load: {len(load_result.missing_keys)}")
    if load_result.unexpected_keys:
        print(f"{model_size}: unexpected keys during load: {len(load_result.unexpected_keys)}")

    model.eval()
    dummy_input = torch.randn(1, 55, config.num_samples * 2)
    export_path = ARTIFACT_DIR / f"wlasl_{model_size}.onnx"

    torch.onnx.export(
        model,
        dummy_input,
        str(export_path),
        export_params=True,
        opset_version=14,
        dynamo=False,
        do_constant_folding=True,
        input_names=["input"],
        output_names=["output"],
    )

    if not export_path.exists() or export_path.stat().st_size == 0:
        raise RuntimeError(f"ONNX export failed for {model_size}")

    final_path = WEB_PUBLIC_DIR / export_path.name
    replace_file(export_path, final_path)
    print(f"Exported {final_path}")
    return final_path


def export_label_files(hf_hub_download, HfApi) -> list[Path]:
    api = HfApi()
    repo_files = api.list_repo_files(repo_id=REPO_ID)
    label_files = select_label_files(repo_files)
    copied: list[Path] = []

    for repo_file in label_files:
        downloaded = download_repo_file(
            hf_hub_download,
            repo_file,
            ARTIFACT_DIR / "labels" / Path(repo_file).parent,
        )
        target = WEB_PUBLIC_DIR / destination_name(repo_file)
        copy_file(downloaded, target)
        copied.append(target)
        print(f"Copied label artifact {target}")

    return copied


def main() -> None:
    ensure_dependencies()
    prepare_dirs()

    import torch
    from huggingface_hub import HfApi, hf_hub_download

    download_repo_file(hf_hub_download, "tgcn_model.py", VENDOR_DIR)
    download_repo_file(hf_hub_download, "configs.py", VENDOR_DIR)
    GCN_muti_att, Config = import_vendor_modules()

    exported_paths = [
        export_model(torch, hf_hub_download, Config, GCN_muti_att, model_size, num_classes)
        for model_size, num_classes in MODEL_SPECS.items()
    ]
    label_paths = export_label_files(hf_hub_download, HfApi)

    missing_outputs = [path for path in exported_paths if not path.exists()]
    if missing_outputs:
        raise RuntimeError(f"Missing exported files: {missing_outputs}")

    print("ONNX export complete.")
    for path in exported_paths + label_paths:
        print(path)


if __name__ == "__main__":
    main()
