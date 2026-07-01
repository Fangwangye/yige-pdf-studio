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
    return yadt_main(args)


if __name__ == "__main__":
    sys.exit(main())
