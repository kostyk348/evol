//! EVOL lexer: splits source into tokens per the Phase-1 grammar.
//! Tokens carry no semantics — surface syntax only.

use std::fmt;

/// Lexical error with the source position, formatted like the Python original.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LexError(pub String);

impl fmt::Display for LexError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for LexError {}

/// Language keywords (from the Phase-1 grammar).
const KEYWORDS: &[&str] = &[
    "lib", "rule", "when", "spawn", "retract", "emit", "if", "then", "else", "seq", "par",
    "choice", "loop", "fun", "and", "or", "not", "forall", "import", "try", "catch", "raise",
    "type", "match", "enum",
];

const TWO_CHAR_OPS: &[&str] = &["=>", ":=", "==", "!=", "<=", ">=", "->"];

/// A token: kind (upper-case keyword or NAME/STR/INT/FLOAT/OP/EOF), text, position.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Token {
    pub kind: String,
    pub text: String,
    pub line: usize,
    pub col: usize,
}

impl fmt::Display for Token {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{} {:?}", self.kind, self.text)
    }
}

/// Python-style `repr` for short strings in error messages (`'{'`, `'@'`).
pub fn py_quote(s: &str) -> String {
    format!("'{s}'")
}

/// Tokenize `src`. The trailing token is always `EOF`.
///
/// # Errors
/// [`LexError`] on unterminated strings/escapes and unexpected characters,
/// with `file:line:col` in the message (same format as the Python lexer).
pub fn tokenize(src: &str, filename: &str) -> Result<Vec<Token>, LexError> {
    let chars: Vec<char> = src.chars().collect();
    let n = chars.len();
    let mut tokens = Vec::new();
    let (mut i, mut line, mut col) = (0usize, 1usize, 1usize);
    let mut buf = String::new();

    while i < n {
        let c = chars[i];
        if c == ' ' || c == '\t' || c == '\r' {
            col += 1;
            i += 1;
            continue;
        }
        if c == '\n' {
            line += 1;
            col = 1;
            i += 1;
            continue;
        }
        // comment to end of line
        if c == '#' {
            while i < n && chars[i] != '\n' {
                col += 1;
                i += 1;
            }
            continue;
        }

        let (start_line, start_col) = (line, col);

        // string
        if c == '"' {
            buf.clear();
            col += 1;
            i += 1; // consume the opening quote
            while i < n && chars[i] != '"' {
                let ch = chars[i];
                if ch == '\\' {
                    col += 1;
                    i += 1;
                    if i < n {
                        let esc = chars[i];
                        buf.push(match esc {
                            'n' => '\n',
                            't' => '\t',
                            '\\' => '\\',
                            '"' => '"',
                            other => other,
                        });
                        col += 1;
                        i += 1;
                    } else {
                        return Err(LexError(format!(
                            "{filename}:{line}:{col} незакрытый escape в строке"
                        )));
                    }
                } else {
                    buf.push(ch);
                    col += 1;
                    i += 1;
                }
            }
            if i >= n {
                return Err(LexError(format!(
                    "{filename}:{start_line}:{start_col} незакрытая строка"
                )));
            }
            col += 1;
            i += 1; // consume the closing quote
            tokens.push(Token {
                kind: "STR".into(),
                text: buf.clone(),
                line: start_line,
                col: start_col,
            });
            continue;
        }

        // number (INT or FLOAT)
        if c.is_ascii_digit() {
            buf.clear();
            buf.push(c);
            col += 1;
            i += 1;
            while i < n && chars[i].is_ascii_digit() {
                buf.push(chars[i]);
                col += 1;
                i += 1;
            }
            let is_float = i + 1 < n && chars[i] == '.' && chars[i + 1].is_ascii_digit();
            if is_float {
                buf.push('.');
                col += 1;
                i += 1;
                while i < n && chars[i].is_ascii_digit() {
                    buf.push(chars[i]);
                    col += 1;
                    i += 1;
                }
                tokens.push(Token {
                    kind: "FLOAT".into(),
                    text: buf.clone(),
                    line: start_line,
                    col: start_col,
                });
            } else {
                tokens.push(Token {
                    kind: "INT".into(),
                    text: buf.clone(),
                    line: start_line,
                    col: start_col,
                });
            }
            continue;
        }

        // identifier / keyword (Unicode alphabetic, like Python's isalpha)
        if c.is_alphabetic() || c == '_' {
            buf.clear();
            buf.push(c);
            col += 1;
            i += 1;
            while i < n && (chars[i].is_alphanumeric() || chars[i] == '_') {
                buf.push(chars[i]);
                col += 1;
                i += 1;
            }
            let word = buf.clone();
            let kind = if KEYWORDS.contains(&word.as_str()) {
                word.to_uppercase()
            } else {
                "NAME".to_string()
            };
            tokens.push(Token {
                kind,
                text: word,
                line: start_line,
                col: start_col,
            });
            continue;
        }

        // two-char operators
        if i + 1 < n {
            let two: String = chars[i..i + 2].iter().collect();
            if TWO_CHAR_OPS.contains(&two.as_str()) {
                tokens.push(Token {
                    kind: "OP".into(),
                    text: two,
                    line: start_line,
                    col: start_col,
                });
                col += 2;
                i += 2;
                continue;
            }
        }

        // one-char operators / punctuation
        if "+-*/<>{}()[],.:=|;".contains(c) {
            tokens.push(Token {
                kind: "OP".into(),
                text: c.to_string(),
                line: start_line,
                col: start_col,
            });
            col += 1;
            i += 1;
            continue;
        }

        return Err(LexError(format!(
            "{filename}:{start_line}:{start_col} неожиданный символ {}",
            py_quote(&c.to_string())
        )));
    }

    tokens.push(Token {
        kind: "EOF".into(),
        text: "<eof>".into(),
        line,
        col,
    });
    Ok(tokens)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn kinds(src: &str) -> Vec<String> {
        tokenize(src, "t")
            .unwrap()
            .iter()
            .map(|t| t.kind.clone())
            .collect()
    }

    #[test]
    fn keywords_and_names() {
        assert_eq!(
            kinds("rule R = when boot => emit x;"),
            vec!["RULE", "NAME", "OP", "WHEN", "NAME", "OP", "EMIT", "NAME", "OP", "EOF"]
        );
    }

    #[test]
    fn numbers_and_strings() {
        assert_eq!(kinds("1 2.5 \"hi\\n\""), vec!["INT", "FLOAT", "STR", "EOF"]);
        let toks = tokenize("2.5", "t").unwrap();
        assert_eq!(toks[0].text, "2.5");
        let toks = tokenize("\"a\\tb\"", "t").unwrap();
        assert_eq!(toks[0].text, "a\tb");
    }

    #[test]
    fn operators_and_comments() {
        assert_eq!(
            kinds("=> := == != <= >= -> + - * / < > { } ( ) [ ] , . : = | ;"),
            vec!["OP"; 25]
                .into_iter()
                .chain(["EOF"].into_iter())
                .collect::<Vec<_>>()
        );
        assert_eq!(kinds("# comment\n1"), vec!["INT", "EOF"]);
    }

    #[test]
    fn errors_have_positions() {
        let e = tokenize("\"oops", "f.evol").unwrap_err();
        assert!(e.0.contains("f.evol:1:1"), "{}", e.0);
        assert!(e.0.contains("незакрытая строка"));
        let e = tokenize("1 @ 2", "f").unwrap_err();
        assert!(e.0.contains("неожиданный символ"));
    }

    #[test]
    fn line_col_tracking() {
        let toks = tokenize("a\n  bb", "t").unwrap();
        assert_eq!((toks[0].line, toks[0].col), (1, 1));
        assert_eq!((toks[1].line, toks[1].col), (2, 3));
    }
}
