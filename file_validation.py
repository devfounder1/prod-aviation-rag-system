"""Validate generated Python without executing it or changing string escapes."""
from __future__ import annotations

import io
from pathlib import Path
import tokenize


def prepare_text(path: Path, content: str) -> str:
    if len(content.encode('utf-8')) > 2_000_000:
        raise ValueError('File exceeds 2 MB output limit')
    if path.suffix.lower() != '.py':
        return content
    try:
        compile(content, str(path), 'exec', dont_inherit=True)
        return content
    except (SyntaxError, ValueError) as original:
        if r'\n' not in content:
            raise ValueError(f'Python не сохранён: {original}. Исправь синтаксис и повтори инструмент.') from original
        # Only repair escaped separators OUTSIDE strings/comments, and only if
        # the original is invalid. Valid code (including regex/raw strings) is untouched.
        offsets = [0]
        for line in content.splitlines(keepends=True):
            offsets.append(offsets[-1] + len(line))
        spans: list[tuple[int, int]] = []
        f_depth = 0
        f_start = 0
        # The tokenizer rejects stray backslashes on newer Python versions.
        # Same-length whitespace lets it locate quoted spans without changing
        # offsets; only the original text is ever repaired or saved.
        shadow = content.replace(r'\r\n', '    ').replace(r'\n', '  ')
        try:
            for token in tokenize.generate_tokens(io.StringIO(shadow).readline):
                if token.type == getattr(tokenize, 'FSTRING_START', -1):
                    if f_depth == 0:
                        f_start = offsets[token.start[0] - 1] + token.start[1]
                    f_depth += 1
                    continue
                if token.type == getattr(tokenize, 'FSTRING_END', -1):
                    f_depth -= 1
                    if f_depth == 0:
                        spans.append((f_start, offsets[token.end[0] - 1] + token.end[1]))
                    continue
                if f_depth:
                    continue
                if token.type in {tokenize.STRING, tokenize.COMMENT}:
                    start = offsets[token.start[0] - 1] + token.start[1]
                    end = offsets[token.end[0] - 1] + token.end[1]
                    if token.type == tokenize.COMMENT and r'\n' in content[start:end]:
                        raise ValueError('Неоднозначные переводы строк в комментарии')
                    spans.append((start, end))
        except (tokenize.TokenError, IndentationError, ValueError) as exc:
            raise ValueError('Python не сохранён: передай настоящие переводы строк между командами; '
                             'экранирование внутри строковых литералов сохрани.') from exc
        pieces: list[str] = []
        cursor = 0
        for start, end in spans:
            pieces.append(content[cursor:start].replace(r'\r\n', '\r\n').replace(r'\n', '\n'))
            pieces.append(content[start:end])
            cursor = end
        pieces.append(content[cursor:].replace(r'\r\n', '\r\n').replace(r'\n', '\n'))
        repaired = ''.join(pieces)
        try:
            compile(repaired, str(path), 'exec', dont_inherit=True)
        except (SyntaxError, ValueError) as exc:
            raise ValueError(f'Python не сохранён: {exc}. Исправь код и повтори инструмент.') from exc
        return repaired
