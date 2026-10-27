# Silica Grammar — v0.2.0

EBNF for the grammar the v0.2.0 parser accepts. `NEWLINE` is a significant token
that terminates statements and is ignored inside `(` … `)` and `[` … `]`.

```ebnf
program        = { NEWLINE | use-decl | func-decl | global-decl } EOF ;

use-decl       = "use" module-path NEWLINE ;                 (* 0.2.0 *)
module-path    = IDENT { "." IDENT } ;
func-decl      = "sfn" IDENT "(" [ param { "," param } ] ")" [ "->" type ] block ;
param          = IDENT [ ":" type ] ;
global-decl    = ("let" | "const") IDENT [ ":" type ] "=" expr NEWLINE ;

type           = "Int" | "Float" | "Bool" | "String" | "Unit" | "List" | "Map" | "Any" ;

block          = "{" { NEWLINE | stmt } [ "fin" ] "}" ;

stmt           = let-stmt | assign-stmt | if-stmt | while-stmt | for-stmt
               | ret-stmt | halt-stmt | builder-stmt | expr-stmt | "fin" ;

let-stmt       = ("let" | "const") IDENT [ ":" type ] "=" expr NEWLINE ;
assign-stmt    = IDENT "=" expr NEWLINE ;
if-stmt        = "si" expr block [ "sino" block ] ;
while-stmt     = "tant" expr block ;
for-stmt       = "per" IDENT "in" expr block ;
ret-stmt       = "ret" [ expr ] NEWLINE ;
halt-stmt      = "halt" [ "(" expr ")" ] NEWLINE ;
expr-stmt      = expr NEWLINE ;
builder-stmt   = postfix-expr block ;                          (* 0.2.0 *)
                 (* statement position only; the head must be a call, and the
                    "{" must be on the same line as the closing ")" *)

expr           = or-expr ;
or-expr        = and-expr { "ou" and-expr } ;
and-expr       = equality { "und" equality } ;
equality       = comparison { ( "==" | "!=" ) comparison } ;
comparison     = additive { ( "<" | "<=" | ">" | ">=" ) additive } ;
additive       = multiplicative { ( "+" | "-" ) multiplicative } ;
multiplicative = unary { ( "*" | "/" | "%" ) unary } ;
unary          = "non" unary | "-" unary | postfix ;
postfix        = primary { "(" [ expr { "," expr } ] ")"
                         | "[" expr "]"
                         | "." IDENT } ;
primary        = INT | FLOAT | STRING | "oui" | "nein" | IDENT
               | "(" expr ")"
               | list-literal | map-literal
               | "sprint" | "dit" | "input" ;   (* usable only as a callee *)

list-literal   = "[" [ expr { "," expr } ] "]" ;
map-literal    = "{" [ entry { "," entry } ] "}" ;
entry          = ( STRING | IDENT ) ":" expr ;
```

## Lexical rules

| Class | Definition |
|---|---|
| `IDENT` | `[A-Za-z_][A-Za-z0-9_]*`, excluding keywords |
| `INT` | `[0-9]+` |
| `FLOAT` | `[0-9]+ "." [0-9]+` with an optional `e[+-]?[0-9]+` exponent |
| `STRING` | `"` characters `"` with escapes `\n \t \r \0 \\ \" \uXXXX` |
| comment | `#` or `//` to end of line |
| operators | `== != <= >= -> < > = + - * / % ( ) { } [ ] , : . ;` |

## Notes on the shape of the grammar

* Braces are mandatory for every block; there is no single-statement body form.
* `sino` must immediately follow an `si` block (a newline between them is fine).
* A `{` in *expression* position starts a map literal; a `{` after a statement
  header starts a block. The parser decides by position, so no ambiguity exists.
* Map keys must be string literals or bare identifiers (shorthand for a string
  key).
* `;` is accepted as an optional statement separator, but a newline is the
  idiomatic terminator.
* An expression cannot continue across a newline unless it is inside `(` or `[`;
  a long expression should be wrapped in parentheses.
