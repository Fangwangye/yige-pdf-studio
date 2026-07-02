from __future__ import annotations

import argparse
import os
import sys

from pdf2zh.pdf2zh import yadt_main


def _patch_argos_translator() -> None:
    """修复 pdf2zh 1.9.11 中 ArgosTranslator 的 bug。

    其 translate() 里 `import argotranslate.translate`（拼写错误）会 ModuleNotFoundError，
    且绕过了 BaseTranslator 的缓存。这里改为正确的 do_translate，并移除坏的 translate 重写，
    使其复用 BaseTranslator.translate（带缓存）。
    """
    try:
        from pdf2zh import translator as _t
    except Exception:
        return
    argos = getattr(_t, "ArgosTranslator", None)
    if argos is None:
        return

    def do_translate(self, text: str) -> str:
        import argostranslate.translate as at

        installed = at.get_installed_languages()
        from_lang = next(x for x in installed if x.code == self.lang_in)
        to_lang = next(x for x in installed if x.code == self.lang_out)
        return from_lang.get_translation(to_lang).translate(text)

    argos.do_translate = do_translate
    if "translate" in argos.__dict__:
        del argos.translate  # 回落到 BaseTranslator.translate（带缓存的正确入口）


def _patch_babeldoc_config(disable_rich_text: bool) -> None:
    """给 babeldoc 的 TranslationConfig 注入默认值（pdf2zh 的 yadt_main 不透传这些）：

    - 始终去掉 BabelDOC 往译文里加的推广水印/横幅。
    - 可选：禁用富文本翻译，减少段内碎片化、改善衔接（实验）。
    """
    try:
        from babeldoc.translation_config import TranslationConfig, WatermarkOutputMode
    except Exception:
        return
    original = TranslationConfig.__init__
    if getattr(original, "_yige_patched", False):
        return

    def __init__(self, *args, **kwargs):  # noqa: N807
        kwargs.setdefault("watermark_output_mode", WatermarkOutputMode.NoWatermark)
        if disable_rich_text:
            kwargs.setdefault("disable_rich_text_translate", True)
        return original(self, *args, **kwargs)

    __init__._yige_patched = True
    TranslationConfig.__init__ = __init__


def _patch_tm_capture(path: str) -> None:
    """捕获翻译记忆：包裹 BaseTranslator.translate，把真实的（原文, 译文）追加到 JSONL。

    覆盖所有 provider（argos 已回落到 BaseTranslator.translate；OpenAI 类重写的是
    do_translate，入口仍是 translate）。多线程下用锁保护文件追加。
    """
    try:
        from pdf2zh.translator import BaseTranslator
    except Exception:
        return
    import json
    import threading

    original = BaseTranslator.translate
    if getattr(original, "_yige_tm", False):
        return
    lock = threading.Lock()

    def translate(self, text, ignore_cache=False):  # noqa: ANN001
        result = original(self, text, ignore_cache)
        try:
            src = (text or "").strip()
            dst = (result or "").strip()
            if src and dst and src != dst and len(src) >= 12:
                line = json.dumps({"src": src, "dst": dst}, ensure_ascii=False)
                with lock, open(path, "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except Exception:
            pass
        return result

    translate._yige_tm = True
    BaseTranslator.translate = translate


def main() -> int:
    parser = argparse.ArgumentParser(description="Run pdf2zh BabelDOC without double-reading prompt files.")
    parser.add_argument("files", nargs="+")
    parser.add_argument("--service", required=True)
    parser.add_argument("--lang-in", dest="lang_in", default="en")
    parser.add_argument("--lang-out", dest="lang_out", default="zh")
    parser.add_argument("--output")
    parser.add_argument("--thread", type=int, default=4)
    parser.add_argument("--pages")
    parser.add_argument("--prompt")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--ignore-cache", action="store_true")
    args = parser.parse_args()

    args.dir = False
    args.raw_pages = [args.pages] if args.pages else []
    if args.service.split(":", 1)[0] == "argos":
        _patch_argos_translator()
    _patch_babeldoc_config(
        disable_rich_text=os.environ.get("YIGE_BABELDOC_RICHTEXT_OFF") == "1"
    )
    tm_path = os.environ.get("YIGE_TM_CAPTURE")
    if tm_path:
        _patch_tm_capture(tm_path)
    return yadt_main(args)


if __name__ == "__main__":
    sys.exit(main())
