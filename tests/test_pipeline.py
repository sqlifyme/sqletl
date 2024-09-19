from sqletl.pipeline import *
from sqletl.datatable import DictDataTable


def test_field():
    f = Field('name->prop->0->>prop2')
    assert f.name == "name"
    assert f.path == "prop[0].prop2"
    assert f.source is None


def test_simple():
    pipe = Pipeline([
        Load('https://geo.api.gouv.fr/communes', {'codePostal': 92160}),
        Map({'population': Field('population'), 'nom': Field('nom')})
    ])
    r = pipe.run().to_dict()
    print(r)
    assert r == [{'population': 63232, 'nom': 'Antony'}]


def test_union():
    pipe = Pipeline([
        Union(
            [
                Load('https://geo.api.gouv.fr/communes', {'codePostal': '92160'})
            ],
            [
                Load('https://geo.api.gouv.fr/communes', {'codePostal': '75008'})
            ]
        ),
        Map({'population': Field('population'), 'nom': Field('nom')})
    ])
    r = pipe.run().to_dict()
    print(r)
    assert r == [{'population': 63232, 'nom': 'Antony'}, {'nom': 'Paris', 'population': 2133111}]


def test_simple_join():
    pipe = Pipeline([
        Load('https://api-adresse.data.gouv.fr/search#features', {'q': "31 av gallieni 92160 antony"}),
        Join(
            [Load('https://geo.api.gouv.fr/communes', {'codePostal': Field('properties->postcode')})]
        ),
        Map({'population': Field('population'), 'nom': Field('nom')})
    ])
    r = pipe.run().to_dict()
    print(r)
    assert r == [{'population': 63232, 'nom': 'Antony'}]


def test_multi_join():
    pipe = Pipeline([
        Table("addr", [
            Alias("addr", [Load('https://api-adresse.data.gouv.fr/search#features', {'q': '31 av gallieni 92160 antony'})])
        ]),
        Table("c", [
            Load("addr"),
            Join(
                [Alias("c", [Load('https://geo.api.gouv.fr/communes', {'codePostal': Field('properties->postcode', 'addr')})])],
                [Condition(Field('population'), '>=', 50000)]
            )
        ]),
        Table("ent", [
            Load("c"),
            Join(
                [Alias("ent", [Load('https://recherche-entreprises.api.gouv.fr/search#results', {'code_postal': Field('codesPostaux->0', 'c')})])]
            )
        ]),
        Load("ent"),
        Map({
            'addr': Field('properties->label', 'addr'),
            'ville': Field('nom', 'c'),
            'nom_complet': Field('nom_complet', 'ent'),
        })
    ])
    r = pipe.run().to_dict()
    print(r)
    assert r[0] == {'addr': '31 Avenue Galliéni 92160 Antony', 'ville': 'Antony', 'nom_complet': 'LA POSTE (DIRECTION GENERALE DE LA POSTE)'}


def test_join_on_tables():
    pipe = Pipeline([
        Alias("t1", [
            Load('file://tests/fixtures/data.csv')
        ]),
        Join(
            [
                Alias("t2", [
                    Load('file://tests/fixtures/data-join.csv')
                ])
            ],
            [Condition(Field('nom', 't2'), '=', Field('nom', 't1'))],
            preload=True
        ),
        Map({"nom": Field("nom", "t1"), "region": Field("region", "t2")})
    ])
    r = pipe.run().to_dict()
    print(r)
    assert r[0] == {'nom': 'paris', 'region': "75"}


def test_equality():
    pipe1 = Pipeline([
        Load('https://api-adresse.data.gouv.fr/search#features', {'q': "31 av gallieni 92160 antony"}),
        Join([
            Load('https://geo.api.gouv.fr/communes', {'codePostal': Field('properties->postcode')})
        ]),
        Map({'population': Field('population'), 'nom': Field('nom')})
    ])

    pipe2 = Pipeline([
        Load('https://api-adresse.data.gouv.fr/search#features', {'q': "31 av gallieni 92160 antony"}),
        Join([
            Load('https://geo.api.gouv.fr/communes', {'codePostal': Field('properties->postcode')})
        ]),
        Map({'population': Field('population'), 'nom': Field('nom')})
    ])

    pipe3 = Pipeline([
        Load('https://api-adresse.data.gouv.fr/search#features', {'q': "different"}),
        Join([
            Load('https://geo.api.gouv.fr/communes', {'codePostal': Field('properties->postcode')})
        ]),
        Map({'population': Field('population'), 'nom': Field('nom')})
    ])

    assert pipe1 == pipe2
    assert pipe1 != pipe3


def test_aggreg():
    pipe = Pipeline([
        Load('https://geo.api.gouv.fr/communes', {'codeDepartement': 92}),
        Aggregate({}, {
            "sum": ['sum', Field('population')]
        })
    ])
    r = pipe.run().to_dict()
    print(r)
    assert r == [{'sum': 1635291}]


def test_group_by():
    pipe = Pipeline([
        Load('https://geo.api.gouv.fr/communes'),
        Aggregate({
            "codeDepartement": Field('codeDepartement')
        }, {
            "sum": ['sum', Field('population')]
        })
    ])
    r = pipe.run().to_dict()
    print(r)
    assert r[0] == {'codeDepartement': '01', 'sum': 663202}


def test_sql():
    pipe = Pipeline([
        Load('https://geo.api.gouv.fr/communes'),
        SQL("SELECT codeDepartement, SUM(population) as sum FROM data GROUP BY codeDepartement")
    ])
    r = pipe.run().to_dict()
    print(r)
    assert r[0] == {'codeDepartement': '01', 'sum': 663202}


def test_csv():
    pipe = Pipeline([
        Load('file://tests/fixtures/data.csv'),
    ])
    r = pipe.run().to_dict()
    print(r)
    assert r[0] == {'nom': 'paris', 'population': '2200000'}


def test_xls():
    pipe = Pipeline([
        Load('file://tests/fixtures/mtcars.xlsx'),
    ])
    r = pipe.run().to_dict()
    print(r)
    assert r[0] == {'model': 'Mazda RX4', 'mpg': 21.0, 'cyl': 6, 'disp': 160.0, 'hp': 110, 'drat': 3.9, 'wt': 2.62, 'qsec': 16.46, 'vs': 0, 'am': 1, 'gear': 4, 'carb': 4}


def test_parquet():
    pipe = Pipeline([
        Load('file://tests/fixtures/Titanic.parquet'),
    ])
    r = pipe.run().to_dict()
    print(r)
    assert r[0] == {'PassengerId': 1, 'Survived': 0, 'Pclass': 3, 'Name': 'Braund, Mr. Owen Harris', 'Sex': 'male', 'Age': 22.0, 'SibSp': 1, 'Parch': 0, 'Ticket': 'A/5 21171', 'Fare': 7.25, 'Cabin': None, 'Embarked': 'S'}, {'PassengerId': 2, 'Survived': 1, 'Pclass': 1, 'Name': 'Cumings, Mrs. John Bradley (Florence Briggs Thayer)', 'Sex': 'female', 'Age': 38.0, 'SibSp': 1, 'Parch': 0, 'Ticket': 'PC 17599', 'Fare': 71.2833, 'Cabin': 'C85', 'Embarked': 'C'}


def test_expand():
    pipe = Pipeline([
        Load('file://tests/fixtures/data.json#expand'),
        Map({"id": Field("id"), "fields": Field("fields")}),
        Expand("fields")
    ])
    r = pipe.run()
    assert r.colnames == ["id", "col1", "col2"]
    r = r.to_dict()
    print(r)
    assert len(r) == 2
    assert r[0] == {'id': 1, 'col1': 'value1', 'col2': 'value2'}
    assert r[1] == {'id': 2, 'col1': 'value3', 'col2': 'value4'}


def test_unnest():
    pipe = Pipeline([
        Load('file://tests/fixtures/data.json#unnest'),
        Map({"sub": Field("sub")}),
        Unnest("sub")
    ])
    r = pipe.run()
    assert r.colnames == ["col1", "col2"]
    r = r.to_dict()
    print(r)
    assert len(r) == 2
    assert r[0] == {"col1": "value1", "col2": "value2"}
    assert r[1] == {"col1": "value3", "col2": "value4"}

    pipe = Pipeline([
        Load('file://tests/fixtures/data.json#unnest2'),
        Map({"sub": Field("sub")}),
        Unnest("sub")
    ])
    r = pipe.run()
    assert r.colnames == ["col1", "col2", "col3"]
    r = r.to_dict()
    print(r)
    assert len(r) == 2
    assert r[0] == {"col1": "value1", "col2": "value2", "col3": None}
    assert r[1] == {"col1": "value3", "col2": "value4", "col3": "value5"}


def test_expression():
    expr = Expression("CONCAT", [Field("col1"), Field("col2")])
    dt = DictDataTable([{"col1": "a", "col2": "b"}])
    assert expr.resolve(dt, next(dt)) == "ab"