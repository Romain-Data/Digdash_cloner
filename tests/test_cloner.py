import xml.etree.ElementTree as ET  # noqa: N817

from defusedxml.ElementTree import fromstring as safe_fromstring

from digdash_cloner.models.clone_result import CloneResult
from digdash_cloner.services.backup_builder import BackupBuilder
from digdash_cloner.services.backup_validator import BackupValidator
from digdash_cloner.services.congress_cloner import CongressCloner
from digdash_cloner.services.dependency_resolver import DependencyResolver
from digdash_cloner.utils.uid_generators import uid_hex, uid_int


def test_uid_hex():
    """Vérifie que la génération d'UID hexadécimal est déterministe."""
    id1 = uid_hex("old_id", "salt")
    id2 = uid_hex("old_id", "salt")
    id3 = uid_hex("old_id", "different_salt")
    assert id1 == id2
    assert id1 != id3
    assert len(id1) == 32


def test_uid_int():
    """Vérifie que la génération d'UID entier est déterministe."""
    id1 = uid_int("old_id", "salt")
    id2 = uid_int("old_id", "salt")
    id3 = uid_int("old_id", "different_salt")
    assert id1 == id2
    assert id1 != id3
    assert id1.isdigit()


def test_dependency_resolver():
    """Vérifie la résolution récursive des dépendances de modèles."""
    # Modèle avec dépendances : m1 -> m2, m2 -> m3, m4 (isolé)
    xml_data = """<TableDataModels>
        <TableDataModel id="m1">
            <JOINDMDS><TableDataModelRef Link="m2"/></JOINDMDS>
        </TableDataModel>
        <TableDataModel id="m2">
            <MERGEDMDS><TableDataModelRef Link="m3"/></MERGEDMDS>
        </TableDataModel>
        <TableDataModel id="m3"></TableDataModel>
        <TableDataModel id="m4"></TableDataModel>
    </TableDataModels>"""

    root = safe_fromstring(xml_data)
    all_models = {m.get("id"): m for m in root.findall("TableDataModel")}

    resolver = DependencyResolver()
    deps = resolver.resolve_deps("m1", all_models)

    assert deps == {"m1", "m2", "m3"}


def test_keep_csv_path_mode():
    """Vérifie que le mode 'keep' protège uniquement le CSVDS sans bloquer le renommage de la catégorie."""
    xml_model = """<TableDataModel id="m1" name="Model 2025">
        <Category Name="EuroPCR/2025" />
        <CSVDS Path="123|DIGDASH//EuroPCR-2025//data.csv" Name="data.csv" />
    </TableDataModel>"""

    cloner = CongressCloner(DependencyResolver())
    id_map = {"m1": "m1_new"}

    # Appel du helper interne pour transformer le XML brut du modèle
    transformed = cloner._transform_model_raw(
        raw=xml_model,
        old_id="m1",
        id_map=id_map,
        csv_path_mode="keep",
        src_year="2025",
        dst_year="2026",
        congress="EuroPCR",
        dst_congress="EuroPCR",
    )

    # On parse le XML résultant pour vérifier le contenu
    root = safe_fromstring(transformed)

    # La catégorie DOIT être mise à jour à 2026
    category = root.find("Category")
    assert category is not None
    assert category.get("Name") == "EuroPCR/2026"

    # Les attributs de CSVDS DOIVENT être conservés intacts (avec 2025)
    csvds = root.find("CSVDS")
    assert csvds is not None
    assert csvds.get("Path") == "123|DIGDASH//EuroPCR-2025//data.csv"
    assert csvds.get("Name") == "data.csv"

    # Le nom du modèle lui-même doit être mis à jour
    assert root.get("name") == "Model 2026"


def test_find_year_container():
    """Vérifie que la recherche de conteneur d'année isole strictement par parent (congrès)."""
    # Structure simulée de la hiérarchie du tableau de bord :
    # - EuroPCR (uid=c1)
    #   - 2025 (uid=y1, parent=c1)
    # - GulfPCR (uid=c2)
    #   - 2025 (uid=y2, parent=c2)
    pages = [
        ET.Element("Dashboard", id="EuroPCR", uid="c1", type="container"),
        ET.Element("Dashboard", id="2025", uid="y1", type="container", parent="c1"),
        ET.Element("Dashboard", id="GulfPCR", uid="c2", type="container"),
        ET.Element("Dashboard", id="2025", uid="y2", type="container", parent="c2"),
    ]

    cloner = CongressCloner(DependencyResolver())

    # Recherche stricte sous EuroPCR (c1)
    res_euro = cloner._find_year_container(pages, year="2025", congress_uid="c1")
    assert res_euro is not None
    assert res_euro.get("uid") == "y1"

    # Recherche stricte sous GulfPCR (c2)
    res_gulf = cloner._find_year_container(pages, year="2025", congress_uid="c2")
    assert res_gulf is not None
    assert res_gulf.get("uid") == "y2"

    # Si congress_uid est None/vide (mono-congrès), il accepte le premier venu en fallback
    res_fallback = cloner._find_year_container(pages, year="2025", congress_uid="")
    assert res_fallback is not None
    assert res_fallback.get("uid") == "y1"

    # Recherche pour un rôle mono-congrès sans conteneur (page simple racine)
    leaf_pages = [ET.Element("Dashboard", id="2025", uid="leaf_2025", position="0")]
    res_leaf = cloner._find_year_container(leaf_pages, year="2025", congress_uid="")
    assert res_leaf is not None
    assert res_leaf.get("uid") == "leaf_2025"


def test_backup_validator_dynamic_years():
    """Vérifie que le validateur est dynamique et n'utilise pas d'années codées en dur."""
    # Modèles de données pour 2028 (cible) et 2027 (autre année)
    dm_root = safe_fromstring("""<TableDataModels>
        <TableDataModel id="dm_2028" name="Inscriptions 2028" />
        <TableDataModel id="dm_2027" name="Inscriptions 2027" />
    </TableDataModels>""")

    # Flux valide pour 2028 qui pointe vers le modèle 2028
    wl_root = safe_fromstring("""<Wallet>
        <Flow uid="flow_ok" name="Mon Flux 2028">
            <Category Name="EuroPCR/2028/" />
            <Input id="1" value="dm_2028" />
        </Flow>
        <Flow uid="flow_bad" name="Mon Flux Invalide">
            <Category Name="EuroPCR/2028/" />
            <Input id="1" value="dm_2027" />
        </Flow>
    </Wallet>""")

    validator = BackupValidator()

    # La fonction interne _collect_warnings doit détecter que flow_bad pointe vers dm_2027 (qui n'est pas 2028)
    warnings = validator._collect_warnings(
        dm_root=dm_root, wl_root=wl_root, congress_list=["EuroPCR"], dst_year="2028"
    )

    assert len(warnings) == 1
    assert "EuroPCR/2028 : 1 flux pointent vers un DM d'une autre année" in warnings[0]


def test_backup_builder_model_manifest_category():
    """Vérifie que BackupBuilder inclut le préfixe de catégorie/millésime dans l'item manifest pour les modèles de données."""
    builder = BackupBuilder()
    new_dm_root = ET.Element("TableDataModels")
    dm_file = ET.Element("file")

    m1 = safe_fromstring("""<TableDataModel id="m_2026_1" name="Refresh data CHAM 2026">
        <Category Name="2026"/>
    </TableDataModel>""")
    m2 = safe_fromstring("""<TableDataModel id="m_2026_2" name="StatsApp CHAM 2026">
        <Category Name="CHAM/2026/"/>
    </TableDataModel>""")
    m3 = safe_fromstring("""<TableDataModel id="m_2026_3" name="Standalone 2026"/>""")

    result = CloneResult(
        congress="CHAM",
        src_year="2025",
        dst_year="2026",
        cloned_models=[m1, m2, m3],
        cloned_flows=[],
        cloned_pages=[],
        id_map={},
        flow_uid_map={},
        page_uid_map={},
    )

    builder._append_models(result, new_dm_root, dm_file)

    items = dm_file.findall("item")
    assert len(items) == 3
    assert items[0].get("id") == "m_2026_1"
    assert items[0].get("name") == "2026/Refresh data CHAM 2026"
    assert items[1].get("id") == "m_2026_2"
    assert items[1].get("name") == "CHAM/2026/StatsApp CHAM 2026"
    assert items[2].get("id") == "m_2026_3"
    assert items[2].get("name") == "Standalone 2026"


def test_backup_builder_page_manifest_path():
    """Vérifie que BackupBuilder inclut le chemin complet (parent/enfant) pour les pages dans le manifest."""
    builder = BackupBuilder()
    new_db_root = ET.Element("Dashboards")
    db_file = ET.Element("file")

    # On simule un conteneur parent (par exemple, '2026') et une page enfant ('Inscriptions')
    parent_page = ET.Element("Dashboard", id="2026", uid="parent_uid", type="container")
    child_page = ET.Element("Dashboard", id="Inscriptions", uid="child_uid", parent="parent_uid")

    result = CloneResult(
        congress="GRCI",
        src_year="2025",
        dst_year="2026",
        cloned_models=[],
        cloned_flows=[],
        cloned_pages=[parent_page, child_page],
        id_map={},
        flow_uid_map={},
        page_uid_map={},
    )

    builder._append_pages(result, new_db_root, db_file)

    items = db_file.findall("item")
    assert len(items) == 2
    assert items[0].get("id") == "parent_uid"
    assert items[0].get("name") == "2026"
    assert items[1].get("id") == "child_uid"
    assert items[1].get("name") == "2026/Inscriptions"
