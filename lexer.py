"""EVOL lexer. Разбивает исходник на токены по грамматике Этапа 1.

Токены не зависят от семантики — только от поверхностного синтаксиса.
"""


class LexError(Exception):
    pass


# Ключевые слова языка (из грамматики Этапа 1)
KEYWORDS = {
    "lib", "rule", "when", "spawn", "retract", "emit", "if", "then", "else",
    "seq", "par", "choice", "loop", "fun", "and", "or", "not", "forall",
    "import", "try", "catch", "raise", "type", "match", "enum",
}

# Двусимвольные операторы
TWO_CHAR_OPS = {"=>", ":=", "==", "!=", "<=", ">=", "->"}
ONE_CHAR_OPS = {"+", "-", "*", "/", "<", ">"}


class Token:
    __slots__ = ("kind", "text", "line", "col")

    def __init__(self, kind, text, line, col):
        self.kind = kind
        self.text = text
        self.line = line
        self.col = col

    def __repr__(self):
        return f"Token({self.kind}, {self.text!r}, {self.line}:{self.col})"


def tokenize(src, filename="<input>"):
    tokens = []
    i = 0
    n = len(src)
    line = 1
    col = 1

    def advance():
        nonlocal i, col
        c = src[i]
        i += 1
        if c == "\n":
            col = 1
        else:
            col += 1
        return c

    while i < n:
        c = src[i]
        if c in " \t\r":
            advance()
            continue
        if c == "\n":
            line += 1
            advance()
            continue
        # комментарий до конца строки
        if c == "#":
            while i < n and src[i] != "\n":
                advance()
            continue

        start_line, start_col = line, col

        # строка
        if c == '"':
            buf = []
            advance()  # съесть открывающую "
            while i < n and src[i] != '"':
                ch = src[i]
                if ch == "\\":
                    advance()
                    if i < n:
                        esc = src[i]
                        buf.append({"n": "\n", "t": "\t", "\\": "\\", '"': '"'}.get(esc, esc))
                        advance()
                    else:
                        raise LexError(f"{filename}:{line}:{col} незакрытый escape в строке")
                else:
                    buf.append(ch)
                    advance()
            if i >= n:
                raise LexError(f"{filename}:{start_line}:{start_col} незакрытая строка")
            advance()  # съесть закрывающую "
            tokens.append(Token("STR", "".join(buf), start_line, start_col))
            continue

        # число (INT или FLOAT)
        if c.isdigit():
            buf = [c]
            advance()
            while i < n and src[i].isdigit():
                buf.append(src[i])
                advance()
            if i < n and src[i] == "." and i + 1 < n and src[i + 1].isdigit():
                buf.append(src[i])
                advance()
                while i < n and src[i].isdigit():
                    buf.append(src[i])
                    advance()
                tokens.append(Token("FLOAT", "".join(buf), start_line, start_col))
            else:
                tokens.append(Token("INT", "".join(buf), start_line, start_col))
            continue

        # идентификатор / ключевое слово
        if c.isalpha() or c == "_":
            buf = [c]
            advance()
            while i < n and (src[i].isalnum() or src[i] == "_"):
                buf.append(src[i])
                advance()
            word = "".join(buf)
            if word in KEYWORDS:
                tokens.append(Token(word.upper(), word, start_line, start_col))
            else:
                tokens.append(Token("NAME", word, start_line, start_col))
            continue

        # двусимвольные операторы
        two = src[i:i + 2]
        if two in TWO_CHAR_OPS:
            tokens.append(Token("OP", two, start_line, start_col))
            advance()
            advance()
            continue

        # односимвольные операторы / пунктуация
        if c in ONE_CHAR_OPS or c in "{}()[],.:=|;":
            tokens.append(Token("OP", c, start_line, start_col))
            advance()
            continue

        raise LexError(f"{filename}:{start_line}:{start_col} неожиданный символ {c!r}")

    tokens.append(Token("EOF", "<eof>", line, col))
    return tokens
