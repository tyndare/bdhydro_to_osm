#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# This script is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# It is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License
# along with it. If not, see <http://www.gnu.org/licenses/>.


import re
import sys
import gzip
import math
import collections

import osgeo
import fiona.crs

import osm

SOURCE = "BDOrtho IGN Hydrographie 3.0 2019-12"
VERBOSE = True

same_value = lambda v:v


uniq_dict={}
def uniq_value(v):
    result = uniq_dict.get(v)
    if result is None:
        uniq_dict[v] = v
        result = v
    return result

def uniq(func):
    return lambda v:uniq_value(func(v))

def capitalize_word(word):
    if word in ("du", "de", "le", "la", "des", "les"):
        word = word.lower()
    elif word != word.upper():
        word = word.capitalize()
    if word.startswith("L'") or word.startswith("D'"):
        word = word[0].lower() + "'" + capitalize_word(word[2:])
    return word

def capitalize_words(words):
    return " ".join(map(capitalize_word, words.split(" ")))

def capitalize_name(name):
    name = name.strip()
    name = "-".join(map(capitalize_words, name.split("-")))
    if name:
        name = name[0].upper() + name[1:]
    return name

def has_tag(tag_name):
    return lambda item:tag_name in item.tags
def hasnt_tag(tag_name):
    return lambda item:tag_name not in item.tags

TagSet    = collections.namedtuple("TagSet", ["key", "value"])
TagAppend = collections.namedtuple("TagAppend", ["key", "value"])
WayNodeIndexAction = collections.namedtuple("WayNodeIndexAction", ["index", "action"])
WayNodesAction = collections.namedtuple("WayNodesAction", ["action"])
IfAction = collections.namedtuple("IfAction", ["test", "action"])
WayNodeReverse = collections.namedtuple("WayNodeReverse", [])


WAY_TAG_ACTIONS = [
    # Version 2 de la BD Ortho Hydrograhpie
    ("NOM", [
        (u"NC" , []),
        (u"NR" , []),
        (u".*" , [TagSet("name", uniq(same_value))]),
    ]),
    ("ARTIF", [
        (u"oui" , [TagSet("waterway", "drain"), TagAppend("note", u"man made waterway")]),
        (u"non" , []),
    ]),
    ("REGIME", [
        (u"intermittent" , [TagSet("intermittent", "yes")]),
        (u"permanent" , []),
    ]),
    ("FRANCHISST", [
        (u"tunnel", [TagSet("tunnel", "yes"), TagSet("layer", "-1")]),
        (u"pont-canal", [TagSet("bridge", "yes"), TagSet("layer", "1")]),
        (u"cascade", [TagSet("waterway", "waterfall")]),
        (u"barrage", [TagAppend("note", u"Barrage"), TagSet("tunnel", "yes"), TagSet("layer", "-1")]),
        (u"ecluse", [TagSet("lock", "yes"),
                   WayNodeIndexAction(0, TagSet("waterway", "lock_gate")),
                   WayNodeIndexAction(-1, TagSet("waterway", "lock_gate")),]),
        (u"NC", []),
    ]),
    ("PREC_ALTI", [
        (".*" , [
            IfAction(has_tag("Z_INI"), WayNodeIndexAction(0, TagSet("ele:accuracy", uniq(same_value)))),
            IfAction(has_tag("Z_FIN"), WayNodeIndexAction(-1, TagSet("ele:accuracy", uniq(same_value)))),
            WayNodesAction(
                IfAction(has_tag("ele"), TagSet("ele:accuracy", uniq(same_value)))),
        ]),
    ]),
    ("Z_INI", [
        (# match values from 0 to 4999
         u"([1-4][0-9][1,3])|([0-9][1,3])", [
            WayNodeIndexAction(0, TagSet("ele", same_value)),
            WayNodeIndexAction(0, TagSet("source:ele", SOURCE)),
        ]),
        (".*", []),
    ]),
    ("Z_FIN", [
        (# match values from 0 to 4999
         u"([1-4][0-9][1,3])|([0-9][1,3])", [
            WayNodeIndexAction(-1, TagSet("ele", same_value)),
            WayNodeIndexAction(-1, TagSet("source:ele", SOURCE)),
        ]),
        (".*", []),
    ]),

    # Version 3 de la BD Ortho Hydrograhpie
    ("NOM_C_EAU", [
        (".*" , [TagSet("name", uniq(capitalize_name))]),
    ]),
    ("LARGEUR", [
        (u"Sans objet", [TagSet("waterway", "stream")]),
        (u"En attente de mise . jour", [TagSet("waterway", "stream")]),
        (u"Entre 0 et 15 m", [TagSet("waterway", "stream")]),
        (u"Entre 15 et 50 m", [TagSet("waterway", "river")]),
        (u"Entre 50 et 250 m", [TagSet("waterway", "river")]),
        (u"Entre 250 et 1250 m", [TagSet("waterway", "river")]),
        (u"Plus de 1250 m", [TagSet("waterway", "river")]),
        (u"Plus de 50 m", [TagSet("waterway", "river")]),
    ]),
    ("FOSSE", [
        ("oui" , [TagSet("waterway", "ditch")]),
        ("non" , []),
    ]),
    ("FICTIF", [
        ("oui" , [
            # En BDTopage, la notion de 'Fictif'="Vrai" ne concerne plus que les tronçons
            # traversant une surface en eau.
            #IfAction(
            #    hasnt_tag("ID_S_HYDRO"),
            #    TagAppend("fixme", u"fictitious waterway ensuring continuity")),
        ]),
        ("non" , []),
    ]),
    ("PREC_PLANI", [
        (".*" , [TagSet("location:accuracy", uniq(same_value))]),
    ]),
    ("POS_SOL", [
        ("-1" , [TagSet("tunnel", "yes"), TagSet("layer", "-1")]),
        ("0" , []),
        ("1" , [TagSet("bridge", "yes"), TagSet("layer", "1")]),
        ("Inconnue" , []),
    ]),
    ("DELIMIT", [
        ("oui" , []),
        ("non" , [TagAppend("fixme", u"unknown location because waterway underground or under dense vegetation")]),
    ]),
    ("DATE_CREAT", [
        (".*" , [TagSet("source:date", lambda v:v.split()[0])]),
    ]),
    ("DATE_MAJ", [
        (".*" , [TagSet("source:date", lambda v:v.split()[0])]),
    ]),
    ("CODE_CARTH", [
        (".*" , [TagSet("ref:sandre", uniq(same_value))]),
    ]),
    ("ETAT", [
        (u"En projet" , [TagAppend("fixme", u"En projet, travaux non démarrés")]),
        (u"En construction" , [TagAppend("fixme", uniq(same_value))]),
        (u"En service" , []),
        (u"Non exploité" , []),
    ]),
    ("NATURE", [
        (u"Ecoulement naturel" , []),
        (u"Aqueduc" , [TagAppend("note", uniq(same_value)),
                     TagSet("bridge", "aqueduct"),
                     TagSet("layer", "1"),]),
        (u"Canal" , [TagAppend("note", uniq(same_value)),
                   TagSet("waterway", "canal"), ]),
        (u"Conduit buse" , [TagAppend("note", uniq(same_value)),
                     TagSet("tunnel", "flooded"),
                     TagSet("layer", "-1"),]),
        (u"Conduit forcé" , [TagAppend("note", uniq(same_value)),
                           TagSet("waterway", "pressurised"),]),
        (u"Delta" , [TagAppend("note", uniq(same_value))]),
        (u"Ecoulement canalisé" , [TagAppend("note", uniq(same_value))]),
        (u"Ecoulement endoréique" , [TagAppend("note", uniq(same_value))]),
        (u"Ecoulement karstique" , [TagAppend("note", uniq(same_value))]),
        (u"Ecoulement phréatique" , [TagAppend("note", uniq(same_value))]),
        (u"Estuaire" , [TagAppend("note", uniq(same_value))]),
        (u"Glacier, névé" , [TagAppend("note", uniq(same_value))]),
        (u"Inconnue" , []),
        (u"Lac" , [TagAppend("note", uniq(same_value))]),
        (u"Lagune" , [TagAppend("note", uniq(same_value))]),
        (u"Mangrove" , [TagAppend("note", uniq(same_value))]),
        (u"Marais" , [TagAppend("note", uniq(same_value))]),
        (u"Mare" , [TagAppend("note", uniq(same_value))]),
        (u"Plan d'eau de gravière" , [TagAppend("note", uniq(same_value))]),
        (u"Plan d'eau de mine" , [TagAppend("note", uniq(same_value))]),
        (u"Réservoir-bassin" , [TagAppend("note", uniq(same_value))]),
        (u"Réservoir-bassin d'orage" , [TagAppend("note", uniq(same_value))]),
        (u"Réservoir-bassin piscicole" , [TagAppend("note", uniq(same_value))]),
        (u"Retenue" , [TagAppend("note", uniq(same_value))]),
        (u"Retenue-barrage" , [TagAppend("note", uniq(same_value))]),
        (u"Retenue-bassin portuaire" , [TagAppend("note", uniq(same_value))]),
        (u"Retenue-digue" , [TagAppend("note", uniq(same_value))]),
    ]),
    ("NAVIGABL", [
        (u"oui" , [TagSet("motorboat", "yes")]),
        (u"non" , []),
    ]),
    ("SENS_ECOUL", [
        (u"Double sens", [TagAppend("note", u"Double sens d'écoulement")]),
        (u"Inconnu", []),
        (u"Sens direct", []),
        (u"Sens inverse", [WayNodeReverse()]),
    ]),
    ("BRAS", [
        (u"Inconnu", []),
        (u"Sans objet", []),
        (u"Principal", []),
        (u"Secondaire", [TagAppend("note", u"Bras secondaire")]),
        (u"Mort", [TagAppend("note", u"Bras mort")]),

    ]),
    ("PERSISTANC", [
        (u"Sec", [TagSet("intermittent", "yes"), TagAppend("note", u"s'écoulant uniquement pendant de fortes précipitations et immédiatement après")]),
        (u"Ephémère", [TagSet("intermittent", "yes"), TagAppend("note", u"s'écoulant pendant des précipitations et immédiatement après")]),
        (u"Intermittent", [TagSet("intermittent", "yes"), TagSet("seasonal", "yes")]),
        (u"Permanent", []),
        (u"Inconnue", []),
    ]),
    ("STATUT", [
        (u"Gelé" , [TagAppend("fixme", u"vérification de sa pertinence en cours par un groupe d'experts du SANDRE")]),
        (u"Validé" ,[]),
    ]),
    ("CODE_HYDRO", [(".*", []),]),
    ("CODE_PAYS", [(".*", []),]),
    ("DATE_CONF", [(".*", []),]),
    ("ID", [(".*", []),]),
    ("ID_C_EAU", [(".*", []),]),
    ("ID_S_HYDRO", [( ".*" , []),]), # id de la surface correspondante
    ("ORIGINE", [( ".*" , []),]),
    ("NUM_ORDRE", [( ".*" , []),]),
    ("CLA_ORDRE", [( ".*" , []),]),
    ("PER_ORDRE", [( ".*" , []),]),
    ("INV_PO_EAU", [( ".*" , []),]),
    ("ID_PO_EAU", [( ".*" , []),]),
    ("ID_ENT_TR", [( ".*" , []),]),
    ("NOM_ENT_TR", [( ".*" , []),]),
    ("SALINITE", [( ".*" , []),]),
    ("PREC_ALTI", [( ".*" , []),]),
    ("SRC_ALTI", [( ".*" , []),]),
    ("SRC_COORD", [( ".*" , []),]),
    ("SOURCE", [( ".*" , []),]),
    ("RES_COULAN", [( ".*" , []),]),
]

WAY_ACTIONS = [
    IfAction(hasnt_tag("waterway"), TagSet("waterway", "stream")),
    IfAction(hasnt_tag("source"), TagSet("source", SOURCE)),
    WayNodesAction(
        IfAction(has_tag("ele"), TagSet("source:ele", SOURCE))),
]

def read_shp_as_osm(shp_path, add_ele_tag=True):
    osm_data = osm.Osm({})
    node_by_coord = {}
    dst_crs = osgeo.osr.SpatialReference()
    dst_crs.ImportFromEPSG(4326)
    with fiona.open(shp_path) as src:
        src_crs = osgeo.osr.SpatialReference()
        src_crs.ImportFromProj4(fiona.crs.to_string(src.crs))
        transformation =  osgeo.osr.CoordinateTransformation(src_crs, dst_crs)
        i = 0
        size = len(src)
        percent = -1
        for item in src:
            i = i + 1
            new_percent = int(100*(i+1)/size)
            if VERBOSE and new_percent > percent:
                percent = new_percent
                sys.stderr.write("{0} % ({1} / {2})\r".format(percent, i, size))
            if item['geometry']['type'] == "LineString":
                way = osm_data.create_way(
                    attrs={},
                    tags={str(key): str(value)
                          for key,value in item['properties'].items()
                          if value is not None})
                coordinates = item["geometry"]["coordinates"]
                for (x,y,z) in coordinates:
                    x,y,z = transformation.TransformPoint(x,y,z)
                    node = node_by_coord.get((x,y))
                    if node is None:
                        node = osm_data.create_node(
                            attrs={'lon':str(x), 'lat':str(y)}, tags={})
                        node_by_coord[(x,y)] = node
                    way.add_node(node)
                if add_ele_tag:
                    for node_index in (0, -1):
                        if coordinates[node_index][2] >= 0 and coordinates[node_index][2] < 5000:
                            osm_data.nodes[way.nodes[node_index]].tags["ele"] = str(z)
    if VERBOSE:
        sys.stderr.write("\n")
    return osm_data


def bearing(node1, node2):
    dy = node2.lat() - node1.lat();
    dx = math.cos(math.pi/180*node1.lat())*(node2.lon() - node1.lon());
    return 180 * math.atan2(dx, dy) / math.pi;

def angle_diff(angle1, angle2):
    return (angle1 - angle2 + 180) % 360 - 180

def start_bearing(way, osm_data):
    return bearing(
        osm_data.nodes[way.nodes[0]],
        osm_data.nodes[way.nodes[1]])

def end_bearing(way, osm_data):
    return bearing(
        osm_data.nodes[way.nodes[-2]],
        osm_data.nodes[way.nodes[-1]])

def ways_angle(way1, way2, osm_data):
    return abs(angle_diff(
        end_bearing(way1, osm_data),
        start_bearing(way2, osm_data)))




def execute_action(action, obj, param, osm_data):
    if type(action) == TagSet:
        value = action.value(param) if callable(action.value) else action.value
        obj.tags[action.key] = value
    elif type(action) == TagAppend:
        value = action.value(param) if callable(action.value) else action.value
        if action.key in obj.tags:
            obj.tags[action.key] = obj.tags[action.key]  + ";" + value
        else:
            obj.tags[action.key] = value
    elif type(action) == WayNodeReverse:
        obj.nodes.reverse()
    elif type(action) == IfAction:
        if action.test(obj):
            execute_action(action.action, obj, param, osm_data)
    elif type(action) == WayNodesAction:
        for node_index in obj.nodes:
            execute_action(
                action.action,
                osm_data.nodes[node_index],
                param, osm_data)
    else:
        assert(type(action) == WayNodeIndexAction)
        execute_action(
            action.action,
            osm_data.nodes[obj.nodes[action.index]],
            param, osm_data)



def modify_item(item, osm_data, item_tag_actions, item_actions):
    for key, values_actions in item_tag_actions:
        if key in item.tags:
            value = item.tags[key]
            found = False
            for pattern, actions in values_actions:
                if pattern==value or re.match(pattern, value, re.IGNORECASE):
                    found = True
                    break
            if found:
                for action in actions:
                    execute_action(action, item, value, osm_data)
                del item.tags[key]
            else:
                raise Exception("unknown value " + key + "=" + value)
    for action in item_actions:
        execute_action(action, item, None, osm_data)

def merge_ways(osm_data):
## FIXME: loops are not handled correctly
## e.g.:   _____
##     ___/     \____
##        \_____/
    node_begins_ways = collections.defaultdict(set)
    node_ends_ways = collections.defaultdict(set)
    for way_id in osm_data.ways:
        way = osm_data.ways[way_id]
        node_begins_ways[way.nodes[0]].add(way_id)
        node_ends_ways[way.nodes[-1]].add(way_id)
    way_merge_ids = {way_id: way_id for way_id in osm_data.ways.keys()}
    def get_merged_id(way_id):
        while way_merge_ids[way_id] != way_id:
            way_id = way_merge_ids[way_id]
        return way_id
    def get_previous_way_of_same_name(way):
        name = way.tags.get("name")
        if name:
            for prev_id in node_ends_ways[way.nodes[0]]:
                prev_way = osm_data.ways[get_merged_id(prev_id)]
                if prev_way.tags.get("name","") == name:
                    return prev_way
        return None
    def get_way_to_merge(way):
        prev_way = get_previous_way_of_same_name(way)
        if prev_way is None:
            if len(node_ends_ways[way.nodes[0]]) == 1:
                prev_id = next(iter(node_ends_ways[way.nodes[0]]))
                prev_way = osm_data.ways[get_merged_id(prev_id)]
            elif len(node_ends_ways[way.nodes[0]]) >= 1:
                prev_ways = [osm_data.ways[get_merged_id(i)]
                             for i in node_ends_ways[way.nodes[0]]]
                prev_ways.sort(key = lambda w: ways_angle(w, way, osm_data))
                prev_way = prev_ways[0]
        if prev_way and (prev_way.tags == way.tags) \
                and (prev_way.nodes[-1] == way.nodes[0]):
            return prev_way
        else:
            return None
    for way_id in list(osm_data.ways.keys()):
        way = osm_data.ways[get_merged_id(way_id)]
        way_to_merge = get_way_to_merge(way)
        if way_to_merge:
            way_to_merge.nodes = way_to_merge.nodes + way.nodes[1:]
            del(osm_data.ways[way_id])
            way_merge_ids[way_id] = way_to_merge.id()

def main():
    if len(sys.argv) > 1:
        filename = sys.argv[1]
        sys.stderr.write("read\n")
        if filename.endswith(".osm"):
            osm_data = osm.OsmParser().parse(sys.argv[1])
        elif filename.endswith(".osm.gz"):
            with gzip.open(sys.argv[1]) as f:
                osm_data = osm.OsmParser().parse_stream(f)
        elif filename.endswith(".shp"):
            osm_data = read_shp_as_osm(sys.argv[1])
        else:
            raise Exception("unsupported input file extension: "  + filename)
    else:
        osm_data = osm.OsmParser().parse_stream(sys.stdin)
    if VERBOSE:
        sys.stderr.write("modify tags\n")
    for way_id in osm_data.ways:
        modify_item(osm_data.ways[way_id], osm_data, WAY_TAG_ACTIONS, WAY_ACTIONS)
    if VERBOSE:
        sys.stderr.write("merge ways\n")
    merge_ways(osm_data)
    sys.stderr.write("write\n")
    writer=osm.OsmWriter(osm_data)
    if len(sys.argv) == 3:
        if sys.argv[2].endswith(".gz"):
            with gzip.open(sys.argv[2],"wt", encoding="utf-8") as f:
                writer.write_to_stream(f)
        else:
            writer.write_to_file(sys.argv[2])
    else:
        writer.write_to_stream(sys.stdout)

if __name__ == '__main__':
    main()
