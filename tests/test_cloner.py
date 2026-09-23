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


def test_backup_builder_parent_dashboard_ref_inserted():
    """Vérifie que BackupBuilder insère le DashboardRef dans le conteneur parent (congrès)."""
    builder = BackupBuilder()
    new_db_root = ET.Element("Dashboards")
    db_file = ET.Element("file")

    # Conteneur parent racine représentant le congrès avec des DashboardRef existants (2025, 2024)
    congress_container = ET.Element("Dashboard", id="EuroPCR", uid="congress_uid", type="container")
    ET.SubElement(congress_container, "DashboardRef", link="year_2025_uid")
    ET.SubElement(congress_container, "DashboardRef", link="year_2024_uid")
    new_db_root.append(congress_container)

    # Page clonée 2026 qui a pour parent le congrès
    year_2026_page = ET.Element("Dashboard", id="2026", uid="year_2026_uid", parent="congress_uid", type="container")

    result = CloneResult(
        congress="EuroPCR",
        src_year="2025",
        dst_year="2026",
        cloned_models=[],
        cloned_flows=[],
        cloned_pages=[year_2026_page],
        id_map={},
        flow_uid_map={},
        page_uid_map={},
    )

    builder._append_pages(result, new_db_root, db_file)

    refs = congress_container.findall("DashboardRef")
    assert len(refs) == 3
    # Le nouveau 2026 doit être inséré en premier
    assert refs[0].get("link") == "year_2026_uid"
    assert refs[1].get("link") == "year_2025_uid"
    assert refs[2].get("link") == "year_2024_uid"


def test_clone_pages_datasource_id_replacement():
    """Vérifie que CongressCloner remplace les IDs de modèles de données (datasource/value/dmId) dans les pages."""
    cloner = CongressCloner(DependencyResolver())
    page = safe_fromstring("""<Dashboard id="General Data" uid="old_p_uid">
        <Base name="Filter" type="dimension" uid="old_portlet_uid">
            <Parameter name="datasource" value="old_dm_id"/>
        </Base>
    </Dashboard>""")

    cloned = cloner._clone_pages(
        pages_to_clone=[page],
        page_uid_map={"old_p_uid": "new_p_uid"},
        portlet_uid_map={"old_portlet_uid": "new_portlet_uid"},
        flow_uid_map={},
        id_map={"old_dm_id": "new_dm_id"},
        src_year="2025",
        dst_year="2026",
        congress="EuroPCR",
        dst_congress="EuroPCR",
        ts="123456789",
    )

    assert len(cloned) == 1
    param = cloned[0].find(".//Parameter[@name='datasource']")
    assert param is not None
    assert param.get("value") == "new_dm_id"


def test_select_flows_priority():
    """Vérifie que la priorité slash '/' est appliquée avant le tiret '-'."""
    cloner = CongressCloner(DependencyResolver())

    flows_xml = """<Wallet>
        <Flow uid="1"><Category Name="EuroPCR/2026/Sub"/><Input id="1" value="dm1"/></Flow>
        <Flow uid="2"><Category Name="EuroPCR-2026"/><Input id="1" value="dm2"/></Flow>
    </Wallet>"""
    root = safe_fromstring(flows_xml)
    all_flows = root.findall("Flow")

    # Si slash présent -> sélectionne uniquement les flux slash
    flows, sep = cloner._select_flows_to_clone(all_flows, "EuroPCR", "2026")
    assert len(flows) == 1
    assert flows[0][0].get("uid") == "1"
    assert sep == "/"

    # Si slash absent -> sélectionne les flux tiret
    flows_dash_xml = """<Wallet>
        <Flow uid="2"><Category Name="EuroPCR-2026"/><Input id="1" value="dm2"/></Flow>
        <Flow uid="3"><Category Name="EuroPCR-2026/Registration"/><Input id="1" value="dm3"/></Flow>
    </Wallet>"""
    root_dash = safe_fromstring(flows_dash_xml)
    flows_dash, sep_dash = cloner._select_flows_to_clone(root_dash.findall("Flow"), "EuroPCR", "2026")
    assert len(flows_dash) == 2
    assert sep_dash == "-"


def test_clone_flows_slash_export_normalization():
    """Vérifie que les catégories avec tiret sont exportées avec un slash '/'."""
    cloner = CongressCloner(DependencyResolver())
    flows_xml = """<Wallet>
        <Flow uid="1" name="F1"><Category Name="EuroPCR-2026"/><Input id="1" value="dm1"/></Flow>
        <Flow uid="2" name="F2"><Category Name="EuroPCR-2026/Registration"/><Input id="1" value="dm2"/></Flow>
    </Wallet>"""
    root = safe_fromstring(flows_xml)
    flows = [(f, f.find("Category").get("Name"), f.find("Input").get("value")) for f in root.findall("Flow")]
    flow_uid_map = {"1": "10", "2": "20"}
    id_map = {"dm1": "dm1_new", "dm2": "dm2_new"}

    cloned = cloner._clone_flows(
        flows_to_clone=flows,
        flow_uid_map=flow_uid_map,
        id_map=id_map,
        congress="EuroPCR",
        src_year="2026",
        dst_year="2026",
        dst_congress="PCRLondonValves",
        ts="12345",
        role_id="role1",
        matched_sep="-",
    )

    assert len(cloned) == 2
    cat1 = cloned[0].find("Category").get("Name")
    cat2 = cloned[1].find("Category").get("Name")
    assert cat1 == "PCRLondonValves/2026"
    assert cat2 == "PCRLondonValves/2026/Registration"


def test_clone_creates_new_target_congress_hierarchy():
    """Vérifie que cloner vers un congrès cible inexistant crée le conteneur congrès et range l'année et les pages dessous."""
    cloner = CongressCloner(DependencyResolver())

    # Dashboard XML simulé avec seulement EuroPCR -> 2026 -> Filters
    euro_congress = ET.Element("Dashboard", id="EuroPCR", uid="c_euro", type="container")
    ET.SubElement(euro_congress, "DashboardRef", link="y_2026")
    year_2026 = ET.Element("Dashboard", id="2026", uid="y_2026", parent="c_euro", type="container")
    ET.SubElement(year_2026, "DashboardRef", link="p_filters")
    page_filters = ET.Element("Dashboard", id="Filters", uid="p_filters", parent="y_2026")

    db_root = ET.Element("Dashboards")
    db_root.extend([euro_congress, year_2026, page_filters])

    flow_elem = safe_fromstring('<Flow uid="f1"><Category Name="EuroPCR/2026"/><Input id="1" value="dm1"/></Flow>')
    wl_root = ET.Element("Wallet")
    wl_root.append(flow_elem)

    dm_elem = safe_fromstring('<TableDataModel id="dm1" name="Data 2026"/>')
    dm_root = ET.Element("TableDataModels")
    dm_root.append(dm_elem)

    from digdash_cloner.models.backup import Backup
    backup = Backup(
        role_id="role1",
        dm_key="dm.xml",
        wl_key="wl.iwt",
        db_key="db.xml",
        bk_key="backup.xml",
        all_files={},
        dm_root=dm_root,
        wl_root=wl_root,
        db_root=db_root,
        bk_root=ET.Element("Backup"),
    )

    result = cloner.clone_congress(
        backup=backup,
        congress="EuroPCR",
        src_year="2026",
        dst_year="2026",
        csv_path_mode="replace",
        dst_congress="PCRLondonValves",
    )

    assert result is not None
    cloned_pages = result.cloned_pages

    # Doit contenir : le conteneur PCRLondonValves, le conteneur 2026 et la page Filters
    ids = [p.get("id") for p in cloned_pages]
    assert "PCRLondonValves" in ids
    assert "2026" in ids
    assert "Filters" in ids

    # Vérification de la parenté
    london_container = next(p for p in cloned_pages if p.get("id") == "PCRLondonValves")
    cloned_year = next(p for p in cloned_pages if p.get("id") == "2026")
    cloned_filters = next(p for p in cloned_pages if p.get("id") == "Filters")

    assert london_container.get("parent") is None or london_container.get("parent") == ""
    assert cloned_year.get("parent") == london_container.get("uid")
    assert cloned_filters.get("parent") == cloned_year.get("uid")


def test_split_dm_ids_by_category_year():
    """Vérifie que les modèles sans l'année dans leur nom mais avec l'année dans <Category> sont bien clonés."""
    cloner = CongressCloner(DependencyResolver())

    m1 = safe_fromstring("""<TableDataModel id="m1" name="Modèle final PCR IP's">
        <Category Name="EuroPCR/2025" />
    </TableDataModel>""")
    m2 = safe_fromstring("""<TableDataModel id="m2" name="Modèle générique partagé">
        <Category Name="Shared" />
    </TableDataModel>""")

    all_models = {"m1": m1, "m2": m2}
    dm_to_clone, dm_shared = cloner._split_dm_ids({"m1", "m2"}, all_models, src_year="2025")

    assert "m1" in dm_to_clone
    assert "m2" in dm_shared





