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