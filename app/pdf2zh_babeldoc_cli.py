from __future__ import annotations

import argparse
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
    return yadt_main(args)


if __name__ == "__main__":
    sys.exit(main())
