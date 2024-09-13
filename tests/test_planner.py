from sqletl.ast import *
from sqletl import pipeline as pl
from sqletl.planner import plan


def test_simple():
    ast = Select(
        fields=[
            Field("nom"),
            Field("population")
        ],
        from_=[
            URL("https://geo.api.gouv.fr/communes")
        ],
        where=Condition(QueryField("codePostal"), "=", Scalar("92160")),
        order_by=[(Field("population"), "DESC")]
    )

    assert plan(ast) == pl.Pipeline([
        pl.Alias('https://geo.api.gouv.fr/communes', [
            pl.Load('https://geo.api.gouv.fr/communes', {'codePostal': '92160'}),
            pl.Map({"?codePostal": "92160"}, append=True)
        ]),
        pl.Map({'nom': pl.Field('nom'), 'population': pl.Field('population')}),
        pl.Sort([(pl.Field('population'), 'DESC')])
    ])


def test_simple2():
    ast = Select(
        fields=[
            Field("nom"),
            Field("population")
        ],
        from_=[
            URL("https://geo.api.gouv.fr/communes")
        ],
        where=And([
            Condition(QueryField("codePostal"), "=", Scalar("92160")),
            Condition(Field("nom"), "=", Scalar("Antony"))
        ])
    )

    assert plan(ast) == pl.Pipeline([
        pl.Alias('https://geo.api.gouv.fr/communes', [
            pl.Load('https://geo.api.gouv.fr/communes', {'codePostal': '92160'}),
            pl.Map({"?codePostal": "92160"}, append=True)
        ]),
        pl.Filter([pl.Condition(pl.Field('nom'), '=', 'Antony')]),
        pl.Map({'nom': pl.Field('nom'), 'population': pl.Field('population')})
    ])


def test_or_condition():
    ast = Select(
        fields=[
            Field("nom"),
            Field("population")
        ],
        from_=[
            URL("https://geo.api.gouv.fr/communes")
        ],
        where=And([
            Or([
                Condition(QueryField("codePostal"), "=", Scalar("92160")),
                Condition(QueryField("codePostal"), "=", Scalar("75008")),
            ]),
            Condition(Field("population"), ">", Scalar(50000))
        ])
    )

    assert plan(ast) == pl.Pipeline([
        pl.Alias('https://geo.api.gouv.fr/communes', [
            pl.Union(
                [
                    pl.Load('https://geo.api.gouv.fr/communes', {'codePostal': '92160'}),
                    pl.Map({"?codePostal": "92160"}, append=True)
                ],
                [
                    pl.Load('https://geo.api.gouv.fr/communes', {'codePostal': '75008'}),
                    pl.Map({"?codePostal": "75008"}, append=True)
                ]
            )
        ]),
        pl.SQL("""SELECT "nom", "population" FROM "data" WHERE (("?codePostal" = '92160' AND "population" > 50000) OR ("?codePostal" = '75008' AND "population" > 50000))""")
    ])


def test_cte():
    ast = With(
        {
            "communes": Select(
                fields=[
                    Field("nom"),
                    Field("population")
                ],
                from_=[
                    URL("https://geo.api.gouv.fr/communes")
                ]
            )
        },
        Select(
            fields=[
                Field("nom")
            ],
            from_=[
                Table("communes")
            ],
            where=Condition(Field("population"), ">", Scalar(50000))
        )
    )
    
    assert plan(ast) == pl.Pipeline([
        pl.Table("communes", [
            pl.Alias('https://geo.api.gouv.fr/communes', [
                pl.Load('https://geo.api.gouv.fr/communes')
            ]),
            pl.Map({'nom': pl.Field('nom'), 'population': pl.Field('population')})
        ]),
        pl.Alias('communes', [
            pl.Load("communes")
        ]),
        pl.Filter([pl.Condition(pl.Field('population'), '>', 50000)]),
        pl.Map({'nom': pl.Field('nom')})
    ])


def test_single_join_via_query():
    ast = Select(
        fields=[
            Field("nom", "c"),
            Field("population", "c")
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

    assert plan(ast) == pl.Pipeline([
        pl.Alias("addr", [
            pl.Load('https://api-adresse.data.gouv.fr/search#features', {'q': '31 av gallieni 92160 antony'}),
            pl.Map({"?q": '31 av gallieni 92160 antony'}, append=True)
        ]),
        pl.Join([
            pl.Alias("c", [
                pl.Load('https://geo.api.gouv.fr/communes', {'codePostal': pl.Field('properties->postcode', 'addr')}),
                pl.Map({"?codePostal": pl.JointField(pl.Field('properties->postcode', 'addr'))}, append=True)
            ])
        ]),
        pl.Map({'nom': pl.Field('nom', 'c'), 'population': pl.Field('population', 'c')})
    ])


def test_single_join_via_condition():
    ast = Select(
        fields=[],
        from_=[
            Join(
                Table("t1"),
                Table("t2"),
                Condition(Field("c1", "t1"), "=", Field("c2", "t2"))
            )
        ]
    )

    assert plan(ast) == pl.Pipeline([
        pl.Alias("t1", [
            pl.Load("t1")
        ]),
        pl.Join([
            pl.Alias("t2", [
                pl.Load('t2')
            ])
        ]),
        pl.Filter([pl.Condition(pl.Field('c1', 't1'), '=', pl.Field('c2', 't2'))])
    ])


def test_join_concat():
    ast = Select(
        fields=["*"],
        from_=[
            Join(
                Table("a"),
                Table("b"),
                Condition(Field("x", "a"), "=", Function("CONCAT", [Field("y", "b"), Field("z", "b")]))
            )
        ]
    )

    assert plan(ast) == pl.Pipeline([
        pl.Alias("a", [
            pl.Load("a")
        ]),
        pl.Join([
            pl.Alias("b", [
                pl.Load('b')
            ])
        ]),
        pl.Filter([pl.Condition(pl.Field('x', 'a'), '=', pl.Expression('CONCAT', [pl.Field('y', 'b'), pl.Field('z', 'b')]))])
    ])


def test_cte_join():
    ast = With(
        {
            "addr": Select(
                fields=[
                    Alias("postcode", Field("properties->postcode"))
                ],
                from_=[
                    URL("https://api-adresse.data.gouv.fr/search#features")
                ],
                where=Condition(QueryField("q"), "=", Scalar("31 av gallieni 92160 antony"))
            )
        },
        Select(
            fields=[
                Field("nom", "c"),
                Field("population", "c")
            ],
            from_=[
                Join(
                    Table("addr"),
                    Alias("c", URL("https://geo.api.gouv.fr/communes")),
                    Condition(QueryField("codePostal", "c"), "=", Field("postcode", "addr"))
                )
            ]
        )
    )

    assert plan(ast) == pl.Pipeline([
        pl.Table("addr", [
            pl.Alias("https://api-adresse.data.gouv.fr/search#features", [
                pl.Load('https://api-adresse.data.gouv.fr/search#features', {'q': '31 av gallieni 92160 antony'}),
                pl.Map({"?q": '31 av gallieni 92160 antony'}, append=True)
            ]),
            pl.Map({'postcode': pl.Field('properties->postcode')})
        ]),
        pl.Alias("addr", [
            pl.Load("addr")
        ]),
        pl.Join([
            pl.Alias("c", [
                pl.Load('https://geo.api.gouv.fr/communes', {'codePostal': pl.Field('postcode', 'addr')}),
                pl.Map({"?codePostal": pl.JointField(pl.Field('postcode', 'addr'))}, append=True)
            ]),
        ]),
        pl.Map({'nom': pl.Field('nom', 'c'), 'population': pl.Field('population', 'c')})
    ])


def test_single_join_multi_select():
    ast = Select(
        fields=[
            Alias('addr', Field("properties->label", "addr")),
            Field("nom", "c"),
            Field("population", "c")
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
    
    assert plan(ast) == pl.Pipeline([
        pl.Alias("addr", [
            pl.Load('https://api-adresse.data.gouv.fr/search#features', {'q': '31 av gallieni 92160 antony'}),
            pl.Map({"?q": '31 av gallieni 92160 antony'}, append=True)
        ]),
        pl.Join([
            pl.Alias("c", [
                pl.Load('https://geo.api.gouv.fr/communes', {'codePostal': pl.Field('properties->postcode', 'addr')}),
                pl.Map({"?codePostal": pl.JointField(pl.Field('properties->postcode', 'addr'))}, append=True)
            ])
        ]),
        pl.Map({
            'addr': pl.Field('properties->label', 'addr'),
            'population': pl.Field('population', 'c'),
            'nom': pl.Field('nom', 'c')
        })
    ])


def test_multi_join():
    ast = Select(
        fields=[
            Alias("addr", Field("properties->label", "addr")),
            Alias("ville", Field("nom", "c")),
            Field("nom_complet", "ent"),
        ],
        from_=[
            Join(
                Alias("addr", URL("https://api-adresse.data.gouv.fr/search#features")),
                Join(
                    Alias("c", URL("https://geo.api.gouv.fr/communes")),
                    Alias("ent", URL("https://recherche-entreprises.api.gouv.fr/search#results")),
                    Condition(QueryField("code_postal", "ent"), "=", Field("codePostaux->0", "c"))
                ),
                Condition(QueryField("codePostal", "c"), "=", Field("properties->postcode", "addr"))
            )
        ],
        where=And([
            Condition(QueryField("q", "addr"), "=", Scalar("31 av gallieni 92160 antony")),
            Condition(Field("population", "c"), ">", Scalar(50000))
        ])
    )
    
    assert plan(ast) == pl.Pipeline([
        pl.Alias("addr", [
            pl.Load('https://api-adresse.data.gouv.fr/search#features', {'q': '31 av gallieni 92160 antony'}),
            pl.Map({"?q": '31 av gallieni 92160 antony'}, append=True)
        ]),
        pl.Join([
            pl.Alias("ent", [
                pl.Load('https://recherche-entreprises.api.gouv.fr/search#results', {'code_postal': pl.Field('codePostaux->0', 'c')}),
                pl.Map({"?code_postal": pl.JointField(pl.Field('codePostaux->0', 'c'))}, append=True)
            ])
        ]),
        pl.Join([
            pl.Alias("c", [
                pl.Load('https://geo.api.gouv.fr/communes', {'codePostal': pl.Field('properties->postcode', 'addr')}),
                pl.Map({"?codePostal": pl.JointField(pl.Field('properties->postcode', 'addr'))}, append=True)
            ])
        ]),
        pl.Filter([pl.Condition(pl.Field('population', 'c'), '>', 50000)]),
        pl.Map({
            'addr': pl.Field('properties->label', 'addr'),
            'ville': pl.Field('nom', 'c'),
            'nom_complet': pl.Field('nom_complet', 'ent'),
        })
    ])


def test_expand():
    ast = Select(
        fields=[
            Field("id"),
            Function("EXPAND", [Field("fields")]),
        ],
        from_=[
            URL("https://example.com")
        ]
    )

    assert plan(ast) == pl.Pipeline([
        pl.Alias('https://example.com', [
            pl.Load('https://example.com')
        ]),
        pl.Map({"id": pl.Field("id"), "fields": pl.Field("fields")}),
        pl.Expand("fields")
    ])


def test_unnest():
    ast = Select(
        fields=[
            Function("UNNEST", [Field("fields")]),
        ],
        from_=[
            URL("https://example.com")
        ]
    )

    assert plan(ast) == pl.Pipeline([
        pl.Alias('https://example.com', [
            pl.Load('https://example.com')
        ]),
        pl.Map({"fields": pl.Field("fields")}),
        pl.Unnest("fields")
    ])


def test_aggregate():
    ast = Select(
        fields=[
            Function("SUM", [Field("population")]),
        ],
        from_=[
            URL("https://geo.api.gouv.fr/communes")
        ],
        where=Condition(QueryField("codeDepartement"), "=", Scalar(92))
    )
    
    assert plan(ast) == pl.Pipeline([
        pl.Alias('https://geo.api.gouv.fr/communes', [
            pl.Load('https://geo.api.gouv.fr/communes', {'codeDepartement': 92}),
            pl.Map({"?codeDepartement": 92}, append=True)
        ]),
        pl.SQL('SELECT SUM("population") FROM "data"')
    ])


def test_group_by():
    ast = Select(
        fields=[
            Field("codeDepartement"),
            Function("SUM", [Field("population")])
        ],
        from_=[
            URL("https://geo.api.gouv.fr/communes")
        ],
        group_by="codeDepartement"
    )

    assert plan(ast) == pl.Pipeline([
        pl.Alias('https://geo.api.gouv.fr/communes', [
            pl.Load('https://geo.api.gouv.fr/communes')
        ]),
        pl.SQL("""SELECT "codeDepartement", SUM("population") FROM "data" GROUP BY codeDepartement""")
    ])