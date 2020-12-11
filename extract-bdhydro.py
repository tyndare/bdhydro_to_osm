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


import sys
import gzip
import os.path
import argparse
import subprocess
import collections
import urllib.request
import xml.sax.saxutils
import unicodedata

import fiona.crs
import osgeo.osr




URL_HYDRO="ftp://BDTOPO_V3_ext:Aish3ho8!!!@ftp3.ign.fr/BDTOPO_3-0_2020-09-15/BDTOPO_3-0_HYDROGRAPHIE_SHP_LAMB93_FXX_2020-09-15.7z"
PATH_SHP="BDTOPO_3-0_HYDROGRAPHIE_SHP_LAMB93_FXX_2020-09-15/BDTOPO/1_DONNEES_LIVRAISON_2020-09-00357/BDT_3-0_SHP_LAMB93_FXX_ED2020-09-15/HYDROGRAPHIE/TRONCON_HYDROGRAPHIQUE.shp"

VERBOSE = True


def extract_troncons_shp(shp_path, search):
    ids_by_xy = collections.defaultdict(set)
    matched_ids = []
    if VERBOSE:
        sys.stderr.write("read {0}\n".format(shp_path))
    with fiona.open(shp_path) as shp:
        proj4 = fiona.crs.to_string(shp.crs)
        size = len(shp)
        percent = -1
        for i, item in shp.items():
            new_percent = int(100*(i+1)/size)
            if VERBOSE and new_percent > percent:
                percent = new_percent
                sys.stderr.write("{0} % ({1} / {2})\r".format(percent, i, size))
            if ((search == item['properties'].get("CODE_CARTH"))
                or
                (strip_accents(item['properties'].get("NOM_C_EAU") or "").lower().find(strip_accents(search).lower()) >= 0)
            ):
                matched_ids.append(i)
            if item['geometry']['type'] == "LineString":
                coordinates = item["geometry"]["coordinates"]
                x1,y1,z1 = coordinates[0]
                x2,y2,z2 = coordinates[-1]
                ids_by_xy[(x1,y1)].add(i)
                ids_by_xy[(x2,y2)].add(i)

        if VERBOSE: sys.stderr.write("\n")

        name = most_frequent([
            shp[i]['properties'].get("NOM_C_EAU")
            for i in matched_ids
            if shp[i]['properties'].get("NOM_C_EAU")
        ]) or "?"
        code_carth = most_frequent([
            shp[i]['properties'].get("CODE_CARTH")
            for i in matched_ids
            if shp[i]['properties'].get("CODE_CARTH")
        ]) or "________"
        if VERBOSE: sys.stderr.write(code_carth + ": " + name  + "\n")

        def is_anonymous(item):
            return (
                (not item['properties'].get("CODE_CARTH"))
                and
                (not item['properties'].get("NOM_C_EAU")))

        if VERBOSE: sys.stderr.write("search main\n")
        main_ids = get_connected_ids(
            root_ids=matched_ids,
            item_by_id=shp,
            ids_by_xy=ids_by_xy,
            upstream_filter=is_anonymous,
            downstream_filter=is_anonymous)

        if VERBOSE: sys.stderr.write("search tributary\n")
        tributary_ids = get_connected_ids(
            root_ids=main_ids,
            item_by_id=shp,
            ids_by_xy=ids_by_xy,
            upstream_filter=lambda item:True,
            downstream_filter=is_anonymous)

        main_items = [shp[i] for i in main_ids]
        tributary_items = [shp[i] for i in tributary_ids]

    return proj4, name, code_carth, main_items, tributary_items

def strip_accents(s):
   return ''.join(c for c in unicodedata.normalize('NFD', s)
                  if unicodedata.category(c) != 'Mn')

def save_items_as_osm(items, transformation, filename):
    if VERBOSE: sys.stderr.write("save {0}\n".format(filename))
    with (gzip.open(filename, "wt", encoding="utf-8") if filename.endswith(".gz")
          else open(filename, "w", encoding="utf-8")) \
    as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<osm version="0.6" upload="false" generator="{0}">\n'.format(os.path.basename(sys.argv[0])))
        min_id = 0
        node_id_by_coord = {}
        for item in items:
            assert(item['geometry']['type'] == "LineString")
            coordinates = item["geometry"]["coordinates"]
            for j,(x,y,z) in enumerate(coordinates):
                if (x,y) not in node_id_by_coord:
                    lon, lat, ele = transformation.TransformPoint(x,y,z)
                    min_id = min_id - 1
                    node_id_by_coord[(x,y)] = min_id
                    if (j==0 or j==(len(coordinates)-1)) and ele >=0 and ele < 5000:
                        f.write('\t<node lon="{0}" lat="{1}" id="{2}">\n'.format(lon,lat,min_id))
                        f.write('\t\t<tag k="ele" v="{0}"/>\n'.format(ele))
                        f.write('\t</node>')
                    else:
                        f.write('\t<node lon="{0}" lat="{1}" id="{2}"/>\n'.format(lon,lat,min_id))
        for item in items:
            min_id = min_id - 1
            f.write('\t<way id="{0}">\n'.format(min_id))
            for x,y,z in item["geometry"]["coordinates"]:
                nd_id = node_id_by_coord[(x,y)]
                f.write('\t\t<nd ref="{0}"/>\n'.format(nd_id))
            for k,v in item['properties'].items():
                if v:
                    f.write('\t\t<tag k={0} v={1}/>\n'.format(
                        xml.sax.saxutils.quoteattr(k),
                        xml.sax.saxutils.quoteattr(str(v))))
            f.write('\t</way>\n')
        f.write('</osm>\n')

def get_proj4_to_osm_transformation(proj4):
    src = osgeo.osr.SpatialReference()
    src.ImportFromProj4(proj4)
    dst = osgeo.osr.SpatialReference()
    dst.ImportFromEPSG(4326)
    return osgeo.osr.CoordinateTransformation(src, dst)


def get_connected_ids(root_ids, item_by_id, ids_by_xy, upstream_filter, downstream_filter):
    UPSTREAM = True
    DOWNSTREAM = False
    checked_xys= {UPSTREAM: set(), DOWNSTREAM: set()}
    xys_to_check = []
    for i in root_ids:
        coordinates = item_by_id[i]["geometry"]["coordinates"]
        x1,y1,z1 = coordinates[0]
        x2,y2,z2 = coordinates[-1]
        xys_to_check.append(((x1,y1), UPSTREAM))
        xys_to_check.append(((x2,y2), DOWNSTREAM))
    result = set(root_ids)
    while len(xys_to_check):
        xy, up_or_down = xys_to_check.pop()
        if xy not in checked_xys[up_or_down]:
            checked_xys[up_or_down].add(xy)
            for i in ids_by_xy[xy]:
                if i not in result:
                    item = item_by_id[i]
                    if (((up_or_down == UPSTREAM) and upstream_filter(item))
                            or
                            ((up_or_down == DOWNSTREAM) and downstream_filter(item))):
                        result.add(i)
                        coordinates = item["geometry"]["coordinates"]
                        x1,y1,z1 = coordinates[0]
                        x2,y2,z2 = coordinates[-1]
                        xys_to_check.append(((x1,y1), UPSTREAM))
                        xys_to_check.append(((x2,y2), DOWNSTREAM))
    return result


def most_frequent(List):
    if len(List):
        return max(set(List), key = List.count)
    else:
        return None


def extract_river(shp_path, search):
    proj4, name, code_carth, main_items, tributary_items = \
        extract_troncons_shp(shp_path, search)
    transformation = get_proj4_to_osm_transformation(proj4)
    prefix_filename = code_carth + " - " + name.replace("/","-")
    main_filename = prefix_filename  + " - main.osm.gz"
    tributary_filename = prefix_filename  + " - tributary.osm.gz"
    save_items_as_osm(main_items, transformation, main_filename)
    save_items_as_osm(tributary_items, transformation, tributary_filename)


def get_bd_hydro_troncons_shp():
    if not os.path.exists(PATH_SHP):
        basename = os.path.basename(URL_HYDRO)
        if not os.path.exists(basename):
            if VERBOSE:
                sys.stderr.write("download {0}\n".format(URL_HYDRO))
            try:
                urllib.request.urlretrieve (URL_HYDRO, basename + ".tmp")
                os.rename(basename + ".tmp", basename)
            finally:
                urllib.request.urlcleanup()
        subprocess.check_call(["7z","x", basename])
    return PATH_SHP


def main(argv):
    parser = argparse.ArgumentParser(description="Extrait le filaire d'une rivière au format OSM")
    parser.add_argument('-s', '--shp', dest='shp', help="Shapefile des tronçons a utiliser")
    parser.add_argument('search', metavar="RECHERCHE",
                        help="Nom du cours d'eau ou Code Carthage (ref:sandre)")
    args = parser.parse_args(argv)
    if args.shp is None:
        args.shp = get_bd_hydro_troncons_shp()
    extract_river(args.shp, args.search)


if __name__ == '__main__':
    main(sys.argv[1:])

