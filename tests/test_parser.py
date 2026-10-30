import pytest
from sqletl.ast import *
from sqletl.parser import parse


def test_simple():
    stmt = """
        SELECT nom, population
        FROM "https://geo.api.gouv.fr/communes"
        WHERE "?codePostal" = 92160 AND nom = 'Antony'
        ORDER BY population DESC
    """
    assert parse(stmt) == Select(
        fields=[
            Field("nom"),
            Field("population")
        ],
        from_=[
            URL("https://geo.api.gouv.fr/communes")
        ],
        where=And([
            Condition(QueryField("codePostal"), "=", Scalar(92160)),
            Condition(Field("nom"), "=", Scalar("Antony"))
        ]),
        order_by=[(Field("population"), "DESC")]
    )


def test_or_condition():
    stmt = """
        SELECT nom, population
        FROM "https://geo.api.gouv.fr/communes"
        WHERE ("?codePostal" = 92160 OR "?codePostal" = 75008) AND population > 50000
    """
    assert parse(stmt) == Select(
        fields=[
            Field("nom"),
            Field("population")
        ],
        from_=[
            URL("https://geo.api.gouv.fr/communes")
        ],
        where=And([
            Or([
                Condition(QueryField("codePostal"), "=", Scalar(92160)),
                Condition(QueryField("codePostal"), "=", Scalar(75008)),
            ]),
            Condition(Field("population"), ">", Scalar(50000))
        ])
    )


def test_cte():
    stmt = """
        WITH communes AS (
            SELECT nom, population
            FROM "https://geo.api.gouv.fr/communes"
        ),
        big_communes AS (
            SELECT nom FROM communes WHERE population > 50000
        )
        SELECT * FROM big_communes
    """
    assert parse(stmt) == With(
        {
            "communes": Select(
                fields=[
                    Field("nom"),
                    Field("population")
                ],
                from_=[
                    URL("https://geo.api.gouv.fr/communes")
                ]
            ),
            "big_communes": Select(
                fields=[
                    Field("nom"),
                ],
                from_=[
                    Table("communes")
                ],
                where=Condition(Field("population"), ">", Scalar(50000))
            )
        },
        Select(
            fields=["*"],
            from_=[
                Table("big_communes")
            ]
        )
    )


def test_single_join():
    stmt = """
        SELECT nom, population
        FROM "https://api-adresse.data.gouv.fr/search#features" addr
        JOIN "https://geo.api.gouv.fr/communes" c ON c."?codePostal" = addr.properties->postcode
        WHERE addr."?q" = '31 av gallieni 92160 antony'
    """
    assert parse(stmt) == Select(
        fields=[
            Field("nom"),
            Field("population")
        ],
        from_=[
            Join(
                Alias("addr", URL("https://api-adresse.data.gouv.fr/search#features")),
                Alias("c", URL("https://geo.api.gouv.fr/communes")),
                Condition(QueryField("codePostal", "c"), "=", Field("properties->postcode", "addr"))
            )
        ],
        where=Condition(QueryField("q", "addr"), "=", Scalar("31 av gallieni 92160 antony"))
    )


def test_join_concat():
    stmt = """
        SELECT * FROM a JOIN b ON a.x = CONCAT(b.y, b.z)
    """
    assert parse(stmt) == Select(
        fields=["*"],
        from_=[
            Join(
                Table("a"),
                Table("b"),
                Condition(Field("x", "a"), "=", Function("CONCAT", [Field("y", "b"), Field("z", "b")]))
            )
        ]
    )


def test_expand():
    stmt = """
        SELECT id, EXPAND(fields)
        FROM "https://example.com"
    """
    assert parse(stmt) == Select(
        fields=[
            Field("id"),
            Function("EXPAND", [Field("fields")]),
        ],
        from_=[
            URL("https://example.com")
        ]
    )

    stmt = """
        SELECT id, EXPAND(fields, 'key', 'value')
        FROM "https://example.com"
    """
    assert parse(stmt) == Select(
        fields=[
            Field("id"),
            Function("EXPAND", [Field("fields"), Scalar("key"), Scalar("value")]),
        ],
        from_=[
            URL("https://example.com")
        ]
    )


def test_aggreg():
    stmt = """
        SELECT SUM(population)
        FROM "https://geo.api.gouv.fr/communes"
        WHERE "?codeDepartement" = 92
    """
    assert parse(stmt) == Select(
        fields=[
            Function("SUM", [Field("population")]),
        ],
        from_=[
            URL("https://geo.api.gouv.fr/communes")
        ],
        where=Condition(QueryField("codeDepartement"), "=", Scalar(92))
    )


def test_group_by():
    stmt = """
        SELECT codeDepartement, SUM(population)
        FROM "https://geo.api.gouv.fr/communes"
    """
    assert parse(stmt) == Select(
        fields=[
            Field("codeDepartement"),
            Function("SUM", [Field("population")])
        ],
        from_=[
            URL("https://geo.api.gouv.fr/communes")
        ]
    )


def test_select_scalar():
    stmt = """
        SELECT 1
    """
    assert parse(stmt) == Select(
        fields=[Scalar(1)]
    )

    stmt = """
        SELECT 1 as "result"
    """
    print(repr(parse(stmt)))
    assert parse(stmt) == Select(
        fields=[Alias("result", Scalar(1))]
    )

    stmt = """
        SELECT nom, 'ville' as type
        FROM "https://geo.api.gouv.fr/communes"
    """
    assert parse(stmt) == Select(
        fields=[
            Field("nom"),
            Alias("type", Scalar("ville"))
        ],
        from_=[
            URL("https://geo.api.gouv.fr/communes")
        ]
    )

def test_comparison_operators():
    stmt = """
        SELECT a FROM t WHERE a <= 1 AND b >= 2 AND c <> 3 AND d NOT LIKE 'x%'
    """
    assert parse(stmt) == Select(
        fields=[Field("a")],
        from_=[Table("t")],
        where=And([
            Condition(Field("a"), "<=", Scalar(1)),
            Condition(Field("b"), ">=", Scalar(2)),
            Condition(Field("c"), "<>", Scalar(3)),
            Condition(Field("d"), "not like", Scalar("x%")),
        ])
    )


def test_null_and_in():
    stmt = """
        SELECT * FROM t WHERE a IS NOT NULL AND b IN (1, 2) AND NOT (c = 1 OR c = 2)
    """
    assert parse(stmt) == Select(
        fields=["*"],
        from_=[Table("t")],
        where=And([
            Condition(Field("a"), "is not", Scalar(None)),
            Condition(Field("b"), "in", SQLExpr("(1, 2)")),
            Not(Or([
                Condition(Field("c"), "=", Scalar(1)),
                Condition(Field("c"), "=", Scalar(2)),
            ])),
        ])
    )


def test_join_types():
    stmt = """
        SELECT * FROM a LEFT JOIN b ON a.x = b.x INNER JOIN c ON b.y = c.y
    """
    assert parse(stmt) == Select(
        fields=["*"],
        from_=[
            Join(
                Table("a"),
                Join(Table("b"), Table("c"), Condition(Field("y", "b"), "=", Field("y", "c"))),
                Condition(Field("x", "a"), "=", Field("x", "b")),
                "LEFT"
            )
        ]
    )


def test_literals():
    stmt = """
        SELECT 1.5, -2, 'it''s', NULL, TRUE
    """
    assert parse(stmt) == Select(
        fields=[Scalar(1.5), Scalar(-2), Scalar("it's"), Scalar(None), Scalar(True)]
    )
    assert str(parse(stmt)) == "SELECT 1.5, -2, 'it''s', NULL, TRUE"


def test_sql_expressions():
    stmt = """
        SELECT a + b AS c, CASE WHEN a > 1 THEN 'x' ELSE 'y' END AS d,
               ROW_NUMBER() OVER (PARTITION BY a ORDER BY b) rn
        FROM t
        GROUP BY a, b HAVING COUNT(*) > 1
        ORDER BY c DESC
        LIMIT 10 OFFSET 5
    """
    assert parse(stmt) == Select(
        fields=[
            Alias("c", SQLExpr("a + b")),
            Alias("d", SQLExpr("CASE WHEN a > 1 THEN 'x' ELSE 'y' END")),
            Alias("rn", WindowFunction(Function("ROW_NUMBER", []), "(PARTITION BY a ORDER BY b)")),
        ],
        from_=[Table("t")],
        group_by=SQLExpr("a, b HAVING COUNT(*) > 1"),
        order_by=[(Field("c"), "DESC")],
        limit="10",
        offset="5"
    )


def test_comments():
    stmt = """
        -- fetch communes
        SELECT nom /* the name */ FROM "https://geo.api.gouv.fr/communes";
    """
    assert parse(stmt) == Select(
        fields=[Field("nom")],
        from_=[URL("https://geo.api.gouv.fr/communes")]
    )


def test_syntax_error():
    for stmt in ("UPDATE t SET a = 1", "SELECT a FROM", "SELECT a FROM t WHERE a ="):
        with pytest.raises(SyntaxError):
            parse(stmt)
