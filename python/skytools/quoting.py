# quoting.py

"""Various helpers for string quoting/unquoting."""

import urllib, re

from skytools.psycopgwrapper import QuotedString

__all__ = [
    "quote_literal", "quote_copy", "quote_bytea_raw",
    "quote_bytea_literal", "quote_bytea_copy", "quote_statement",
    "quote_ident", "quote_fqident", "quote_json",
    "db_urlencode", "db_urldecode", "unescape", "unescape_copy"
]

# 
# SQL quoting
#

def quote_literal(s):
    """Quote a literal value for SQL.
    
    Surronds it with single-quotes.
    """

    if s == None:
        return "null"
    s = QuotedString(str(s))
    return str(s)

def quote_copy(s):
    """Quoting for copy command."""

    if s == None:
        return "\\N"
    s = str(s)
    s = s.replace("\\", "\\\\")
    s = s.replace("\t", "\\t")
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "\\r")
    return s

def quote_bytea_raw(s):
    """Quoting for bytea parser."""

    if s == None:
        return None
    return s.replace("\\", "\\\\").replace("\0", "\\000")

def quote_bytea_literal(s):
    """Quote bytea for regular SQL."""

    return quote_literal(quote_bytea_raw(s))

def quote_bytea_copy(s):
    """Quote bytea for COPY."""

    return quote_copy(quote_bytea_raw(s))

def quote_statement(sql, dict):
    """Quote whole statement.

    Data values are taken from dict.
    """
    xdict = {}
    for k, v in dict.items():
        xdict[k] = quote_literal(v)
    return sql % xdict

# reserved keywords
_ident_kwmap = {
"all":1, "analyse":1, "analyze":1, "and":1, "any":1, "array":1, "as":1,
"asc":1, "asymmetric":1, "both":1, "case":1, "cast":1, "check":1, "collate":1,
"column":1, "constraint":1, "create":1, "current_date":1, "current_role":1,
"current_time":1, "current_timestamp":1, "current_user":1, "default":1,
"deferrable":1, "desc":1, "distinct":1, "do":1, "else":1, "end":1, "except":1,
"false":1, "for":1, "foreign":1, "from":1, "grant":1, "group":1, "having":1,
"in":1, "initially":1, "intersect":1, "into":1, "leading":1, "limit":1,
"localtime":1, "localtimestamp":1, "new":1, "not":1, "null":1, "off":1,
"offset":1, "old":1, "on":1, "only":1, "or":1, "order":1, "placing":1,
"primary":1, "references":1, "returning":1, "select":1, "session_user":1,
"some":1, "symmetric":1, "table":1, "then":1, "to":1, "trailing":1, "true":1,
"union":1, "unique":1, "user":1, "using":1, "when":1, "where":1,
}

_ident_bad = re.compile(r"[^a-z0-9_]")
def quote_ident(s):
    """Quote SQL identifier.

    If is checked against weird symbols and keywords.
    """

    if _ident_bad.search(s) or s in _ident_kwmap:
        s = '"%s"' % s.replace('"', '""')
    return s

def quote_fqident(s):
    """Quote fully qualified SQL identifier.

    The '.' is taken as namespace separator and
    all parts are quoted separately
    """
    return '.'.join(map(quote_ident, s.split('.', 1)))

#
# quoting for JSON strings
#

_jsre = re.compile(r'[\x00-\x1F\\/"]')
_jsmap = { "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r",
    "\t": "\\t", "\\": "\\\\", '"': '\\"',
    "/": "\\/",   # to avoid html attacks
}

def _json_quote_char(m):
    c = m.group(0)
    try:
        return _jsmap[c]
    except KeyError:
        return r"\u%04x" % ord(c)

def quote_json(s):
    """JSON style quoting."""
    if s is None:
        return "null"
    return '"%s"' % _jsre.sub(_json_quote_char, s)

#
# Database specific urlencode and urldecode.
#

def db_urlencode(dict):
    """Database specific urlencode.

    Encode None as key without '='.  That means that in "foo&bar=",
    foo is NULL and bar is empty string.
    """

    elem_list = []
    for k, v in dict.items():
        if v is None:
            elem = urllib.quote_plus(str(k))
        else:
            elem = urllib.quote_plus(str(k)) + '=' + urllib.quote_plus(str(v))
        elem_list.append(elem)
    return '&'.join(elem_list)

def db_urldecode(qs):
    """Database specific urldecode.

    Decode key without '=' as None.
    This also does not support one key several times.
    """

    res = {}
    for elem in qs.split('&'):
        if not elem:
            continue
        pair = elem.split('=', 1)
        name = urllib.unquote_plus(pair[0])

        # keep only one instance around
        name = intern(name)

        if len(pair) == 1:
            res[name] = None
        else:
            res[name] = urllib.unquote_plus(pair[1])
    return res

#
# Remove C-like backslash escapes
#

_esc_re = r"\\([0-7][0-7][0-7]|.)"
_esc_rc = re.compile(_esc_re)
_esc_map = {
    't': '\t',
    'n': '\n',
    'r': '\r',
    'a': '\a',
    'b': '\b',
    "'": "'",
    '"': '"',
    '\\': '\\',
}

def _sub_unescape(m):
    v = m.group(1)
    if len(v) == 1:
        return _esc_map[v]
    else:
        return chr(int(v, 8))

def unescape(val):
    """Removes C-style escapes from string."""
    return _esc_rc.sub(_sub_unescape, val)

def unescape_copy(val):
    """Removes C-style escapes, also converts "\N" to None."""
    if val == r"\N":
        return None
    return unescape(val)


#
# parse logtriga partial sql
#

class _logtriga_parser:
    token_re = r"""
        [ \t\r\n]*
        ( [a-z][a-z0-9_]*
        | ["] ( [^"\\]+ | \\. )* ["]
        | ['] ( [^'\\]+ | \\. | [']['] )* [']
        | [^ \t\r\n]
        )"""
    token_rc = None

    def tokenizer(self, sql):
        if not _logtriga_parser.token_rc:
            _logtriga_parser.token_rc = re.compile(self.token_re, re.X | re.I)
        rc = self.token_rc

        pos = 0
        while 1:
            m = rc.match(sql, pos)
            if not m:
                break
            pos = m.end()
            yield m.group(1)

    def unquote_data(self, fields, values):
        # unquote data and column names
        data = {}
        for k, v in zip(fields, values):
            if k[0] == '"':
                k = unescape(k[1:-1])
            if len(v) == 4 and v.lower() == "null":
                v = None
            elif v[0] == "'":
                v = unescape(v[1:-1])
            data[k] = v
        return data

    def parse_insert(self, tk, fields, values):
        # (col1, col2) values ('data', null)
        if tk.next() != "(":
            raise Exception("syntax error")
        while 1:
            fields.append(tk.next())
            t = tk.next()
            if t == ")":
                break
            elif t != ",":
                raise Exception("syntax error")
        if tk.next().lower() != "values":
            raise Exception("syntax error")
        if tk.next() != "(":
            raise Exception("syntax error")
        while 1:
            t = tk.next()
            if t == ")":
                break
            if t == ",":
                continue
            values.append(t)
        tk.next()

    def parse_update(self, tk, fields, values):
        # col1 = 'data1', col2 = null where pk1 = 'pk1' and pk2 = 'pk2'
        while 1:
            fields.append(tk.next())
            if tk.next() != "=":
                raise Exception("syntax error")
            values.append(tk.next())
            
            t = tk.next()
            if t == ",":
                continue
            elif t.lower() == "where":
                break
            else:
                raise Exception("syntax error")
        while 1:
            t = tk.next()
            fields.append(t)
            if tk.next() != "=":
                raise Exception("syntax error")
            values.append(tk.next())
            t = tk.next()
            if t.lower() != "and":
                raise Exception("syntax error")

    def parse_delete(self, tk, fields, values):
        # pk1 = 'pk1' and pk2 = 'pk2'
        while 1:
            t = tk.next()
            if t == "and":
                continue
            fields.append(t)
            if tk.next() != "=":
                raise Exception("syntax error")
            values.append(tk.next())

    def parse_sql(self, op, sql):
        tk = self.tokenizer(sql)
        fields = []
        values = []
        try:
            if op == "I":
                self.parse_insert(tk, fields, values)
            elif op == "U":
                self.parse_update(tk, fields, values)
            elif op == "D":
                self.parse_delete(tk, fields, values)
            raise Exception("syntax error")
        except StopIteration:
            # last sanity check
            if len(fields) == 0 or len(fields) != len(values):
                raise Exception("syntax error")

        return self.unquote_data(fields, values)

def parse_logtriga_sql(op, sql):
    """Parse partial SQL used by logtriga() back to data values.

    Parser has following limitations:
    - Expects standard_quoted_strings = off
    - Does not support dollar quoting.
    - Does not support complex expressions anywhere. (hashtext(col1) = hashtext(val1))
    - WHERE expression must not contain IS (NOT) NULL
    - Does not support updateing pk value.

    Returns dict of col->data pairs.
    """
    return _logtriga_parser().parse_sql(op, sql)

