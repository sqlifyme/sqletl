from sqletl.pipeline import *


def test_field():
    f = Field('name->prop->0->>prop2')
    assert f.name == "name"
    assert f.path == "prop[0].prop2"
    assert f.source is None


def test_simple():
    pipe = Pipeline([
        Load('https://api-adresse.data.gouv.fr/search#features', {'q': "31 av gallieni 92160 antony"}),
        Join([
            Load('https://geo.api.gouv.fr/communes', {'codePostal': Field('properties->postcode')})
        ]),
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


def test_join():
    pipe = Pipeline([
        CreateTable("addr", [
            Load('https://api-adresse.data.gouv.fr/search#features', {'q': '31 av gallieni 92160 antony'})
        ]),
        CreateTable("c", [
            Load("addr"),
            Join([
                Load('https://geo.api.gouv.fr/communes', {'codePostal': Field('properties->postcode', 'addr')}),
                Filter([Condition(Field('population'), '>=', 50000)])
            ])
        ]),
        CreateTable("ent", [
            Load("c"),
            Join([
                Load('https://recherche-entreprises.api.gouv.fr/search#results', {'code_postal': Field('codesPostaux->0', 'c')})
            ])
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


def test_file():
    pipe = Pipeline([
        Load('file://tests/fixtures/data.csv'),
    ])
    r = pipe.run().to_dict()
    print(r)
    assert r[0] == {'nom': 'paris', 'population': '2200000'}


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