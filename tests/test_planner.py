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
        pl.Load('https://geo.api.gouv.fr/communes', {'codePostal': '92160'}),
        pl.Map({
            'nom': pl.Field('nom'),
            'population': pl.Field('population')
        }),
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
        pl.Load('https://geo.api.gouv.fr/communes', {'codePostal': '92160'}),
        pl.Filter([pl.Condition(pl.Field('nom'), '=', 'Antony')]),
        pl.Map({
            'nom': pl.Field('nom'),
            'population': pl.Field('population')
        })
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
            Condition(Field("population"), ">", Scalar("50000"))
        ])
    )

    assert plan(ast) == pl.Pipeline([
        pl.Union(
            [
                pl.Load('https://geo.api.gouv.fr/communes', {'codePostal': '92160'})
            ],
            [
                pl.Load('https://geo.api.gouv.fr/communes', {'codePostal': '75008'})
            ]
        ),
        pl.Filter([pl.Condition(pl.Field('population'), '>', "50000")]),
        pl.Map({
            'nom': pl.Field('nom'),
            'population': pl.Field('population')
        })
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
        pl.CreateTable("communes", [
            pl.Load('https://geo.api.gouv.fr/communes'),
            pl.Map({
                'nom': pl.Field('nom'),
                'population': pl.Field('population')
            })
        ]),
        pl.Load("communes"),
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
        pl.Table("addr", [
            pl.Load('https://api-adresse.data.gouv.fr/search#features', {'q': '31 av gallieni 92160 antony'})
        ]),
        pl.Join([
            pl.Table("c", [
                pl.Load('https://geo.api.gouv.fr/communes', {'codePostal': pl.Field('properties->postcode', 'addr')})
            ])
        ]),
        pl.Map({
            'nom': pl.Field('nom', 'c'),
            'population': pl.Field('population', 'c')
        })
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
        pl.Load("t1"),
        pl.Join([
            pl.Load('t2'),
        ]),
        pl.Filter([pl.Condition(pl.Field('c1', 't1'), '=', pl.Field('c2', 't2'))])
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
        pl.CreateTable("addr", [
            pl.Load('https://api-adresse.data.gouv.fr/search#features', {'q': '31 av gallieni 92160 antony'}),
            pl.Map({'postcode': pl.Field('properties->postcode')})
        ]),
        pl.Load("addr"),
        pl.Join([
            pl.Table("c", [
                pl.Load('https://geo.api.gouv.fr/communes', {'codePostal': pl.Field('postcode', 'addr')}),
            ]),
        ]),
        pl.Map({
            'nom': pl.Field('nom', 'c'),
            'population': pl.Field('population', 'c')
        })
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
        pl.Table("addr", [
            pl.Load('https://api-adresse.data.gouv.fr/search#features', {'q': '31 av gallieni 92160 antony'})
        ]),
        pl.Join([
            pl.Table("c", [
                pl.Load('https://geo.api.gouv.fr/communes', {'codePostal': pl.Field('properties->postcode', 'addr')}),
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
        pl.Table("addr", [
            pl.Load('https://api-adresse.data.gouv.fr/search#features', {'q': '31 av gallieni 92160 antony'})
        ]),
        pl.Join([
            pl.Table("c", [
                pl.Load('https://geo.api.gouv.fr/communes', {'codePostal': pl.Field('properties->postcode', 'addr')}),
            ]),
            pl.Filter([pl.Condition(pl.Field('population', 'c'), '>', 50000)])
        ]),
        pl.Join([
            pl.Table("ent", [
                pl.Load('https://recherche-entreprises.api.gouv.fr/search#results', {'code_postal': pl.Field('codePostaux->0', 'c')})
            ])
        ]),
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
        pl.Load('https://example.com'),
        pl.Map({"id": "id", "fields": "fields"}),
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
        pl.Load('https://example.com'),
        pl.Map({"fields": "fields"}),
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
        pl.Load('https://geo.api.gouv.fr/communes', {'codeDepartement': 92}),
        pl.Aggregate({}, {
            "sum": ['sum', pl.Field('population')]
        })
    ])


def test_group_by():
    ast = Select(
        fields=[
            Field("codeDepartement"),
            Function("SUM", [Field("population")])
        ],
        from_=[
            URL("https://geo.api.gouv.fr/communes")
        ]
    )

    assert plan(ast) == pl.Pipeline([
        pl.Load('https://geo.api.gouv.fr/communes'),
        pl.Aggregate({
            "codeDepartement": pl.Field('codeDepartement')
        }, {
            "sum": ['sum', pl.Field('population')]
        })
    ])