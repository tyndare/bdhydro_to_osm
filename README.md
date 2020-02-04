
# BDHydro to OSM

Extraction au format OSM du filaire d'une rivière et de ses affluents depuis la BD Topo Hydrographie de l'IGN.

## Attention

L'exécution du script nécessite 9 Go d'exspace disque pour
télécharger la BD Hydro (700 Mo) de la France (métropole) 
et la décompresser (7.6 Go)

## Exemple

Extraction de la rivière l'Alze (ref:sandre = O5200600):

```bash
./extract-bdhydro.py O5200600

./modify-bdhydro-osmtags.py "O5200600 - l'Alze - tributary.osm.gz" "L'Alze.osm.gz"

josm "L'Alze.osm.gz"
```
    
## Sélection sous JOSM

Sous JOSM, je trouvre pratique de pouvoir sélectionner les chemins connectés
au chemin déjà sélectionné an lancant la recherche de l'expression suivante:
```
    parent (child (selected))
```

## BD Topo Hydrographie

La BD Topo Hydrographie est disponible sur le site de l'IGN:

https://geoservices.ign.fr/documentation/diffusion/telechargement-donnees-libres.html

Le format de la base est décrit dans le document
[DC_BDTOPO_3-0.pdf](https://geoservices.ign.fr/ressources_documentaires/Espace_documentaire/BASES_VECTORIELLES/BDTOPO/DC_BDTOPO_3-0.pdf)
section 9. Hydrographie, page 109.
