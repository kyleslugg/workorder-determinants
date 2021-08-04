from qgis.core import *
from qgis.PyQt.QtGui import *
from qgis.PyQt.QtCore import *
from qgis.gui import *
import qgis.utils
import os
from os import path
import os.path
import sys

addresses_layer_path = '/Users/kyleslugg/Documents/NYCHA/Misc/Data_Experimentation/address_points/NYCHA_Address_Points.geojson'
buildings_layer_path = '/Users/kyleslugg/Documents/NYCHA/Misc/Data_Experimentation/NYCHA_Buildings/NYCHA_Buildings.shp'


alayer = QgsVectorLayer(addresses_layer_path, "NYCHA Addresses", "ogr")
if not alayer.isValid():
    print("Addresses layer failed to load!")
else:
    if alayer not in list(QgsProject.instance().mapLayers().values()):
        QgsProject.instance().addMapLayer(alayer)
    
blayer = QgsVectorLayer(buildings_layer_path, "NYCHA Buildings", "ogr")
if not alayer.isValid():
    print("Buildings layer failed to load!")
else:
    if blayer not in QgsProject.instance().mapLayers().values():
        QgsProject.instance().addMapLayer(blayer)

#---------------------------------------------------------------------------
    
def get_consolidation_crosswalk(buildings_layer=blayer, tds_att='TDS_NUM', cons_tds_att='CONS_TDS'):
    features = buildings_layer.getFeatures()
    
    consolidations = dict()
    dev_to_cons = dict()
    
    for feature in features:
        if feature[cons_tds_att] not in consolidations.keys():
            consolidations[feature[cons_tds_att]] = [feature[tds_att]]
        elif feature[tds_att] not in consolidations[feature[cons_tds_att]]:
            consolidations[feature[cons_tds_att]].append(feature[tds_att])
        else:
            pass
            
        if feature[tds_att] not in dev_to_cons.keys():
            dev_to_cons[feature[tds_att]] = feature[cons_tds_att]
            
    
    return consolidations, dev_to_cons



def enrich_addresses(dev_to_cons_dict=None, address_layer=alayer, tds_att='TDS_NUM'):
    
    def has_mo(feature, facility_field='FACILITY'):
        if feature[facility_field] == NULL:
            return False
        elif str(feature[facility_field]).find('SATELLITE') > -1:
            return False
        elif str(feature[facility_field]).find('DEVELOPMENT MANAGEMENT OFFICE') > -1:
            return True
        else:
            return False
    
    field_names = [field.name() for field in address_layer.fields()]
 
    if 'HAS_MO' not in field_names:
        address_layer.dataProvider().addAttributes([QgsField("HAS_MO",QVariant.Bool)])
    if 'CONS_TDS' not in field_names:
        address_layer.dataProvider().addAttributes([QgsField("CONS_TDS",QVariant.String)])
    
    address_layer.updateFields()
    
    features = address_layer.getFeatures()
    
    with edit(address_layer):
        for feature in features:
            feature.setAttribute('HAS_MO', has_mo(feature, 'FACILITY'))
            feature.setAttribute('CONS_TDS', dev_to_cons_dict[feature['TDS_NUM']])
            address_layer.updateFeature(feature)


def enrich_buildings(address_layer=alayer, buildings_layer=blayer):
    if 'CONS_TDS' not in [field.name() for field in address_layer.fields()]:
        address_layer = enrich_addresses(address_layer)
    
    if 'HAS_MO' not in [field.name() for field in buildings_layer.fields()]:
        buildings_layer.dataProvider().addAttributes([QgsField("HAS_MO",QVariant.Bool)])
        buildings_layer.updateFields()
        
    address_layer.selectByExpression('"HAS_MO" = True', QgsVectorLayer.SetSelection)
    mo_addresses = address_layer.selectedFeatures()
    
    with edit(buildings_layer):
        buildings_with_management_offices = [(feature['TDS_NUM'], feature['BLDG_NUM']) for feature in mo_addresses]
        
        for feature in buildings_layer.getFeatures():
            if (feature['TDS_NUM'], feature['BLDG_NUM']) in buildings_with_management_offices:
                feature.setAttribute('HAS_MO',True)
            else:
                feature.setAttribute('HAS_MO', False)
            buildings_layer.updateFeature(feature)

       
def compute_distances(cons_to_dev_dict=None, address_layer=alayer, buildings_layer=blayer):
    
    def compute_address_distances(cons_tds):
        cons_addresses = processing.run("native:extractbyexpression", {'INPUT':address_layer.dataProvider().dataSourceUri(),
                                        'EXPRESSION':f''' "CONS_TDS" = '{cons_tds}' ''',
                                        'OUTPUT':'TEMPORARY_OUTPUT'})['OUTPUT']
        #QgsProject.instance().addMapLayer(cons_addresses)
        
        mo_address = processing.run("native:extractbyexpression", {'INPUT':cons_addresses,
                                        'EXPRESSION':f''' "HAS_MO" = True ''',
                                        'OUTPUT':'TEMPORARY_OUTPUT'})['OUTPUT']
        #cons_addresses_source_string = cons_addresses.dataProvider().dataSourceUri().replace('memory?geometry=Point','memory:\\geometry=Point?')+f'&uid=\{{}\}''
        
        augmented_cons_addresses = processing.run("qgis:distancetonearesthubpoints", {'INPUT':cons_addresses,
                                                   'HUBS':mo_address,
                                                   'FIELD':'OBJECTID','UNIT':2,'OUTPUT':'TEMPORARY_OUTPUT'})['OUTPUT']
        
        ids = QgsVectorLayerUtils.getValues(augmented_cons_addresses, 'OBJECTID')[0]
        hub_ids = QgsVectorLayerUtils.getValues(augmented_cons_addresses, 'HubName')[0]
        hub_dist = QgsVectorLayerUtils.getValues(augmented_cons_addresses, 'HubDist')[0]
        
        return list(zip(ids, hub_ids, hub_dist))
        
    def compute_building_distances(cons_tds, bldg_centroids):
        
        cons_buildings = processing.run("native:extractbyexpression", {'INPUT':bldg_centroids,
                                        'EXPRESSION':f''' "CONS_TDS" = '{cons_tds}' ''',
                                        'OUTPUT':'TEMPORARY_OUTPUT'})['OUTPUT']
        #QgsProject.instance().addMapLayer(cons_addresses)
        
        mo_building = processing.run("native:extractbyexpression", {'INPUT':cons_buildings,
                                        'EXPRESSION':f''' "HAS_MO" = 1 ''',
                                        'OUTPUT':'TEMPORARY_OUTPUT'})['OUTPUT']
        #cons_addresses_source_string = cons_addresses.dataProvider().dataSourceUri().replace('memory?geometry=Point','memory:\\geometry=Point?')+f'&uid=\{{}\}''
        
        
        try:
            augmented_cons_buildings = processing.run("qgis:distancetonearesthubpoints", {'INPUT':cons_buildings,
                                                       'HUBS':mo_building,
                                                       'FIELD':'OBJECTID_1','UNIT':2,'OUTPUT':'TEMPORARY_OUTPUT'})['OUTPUT']
            
            ids = QgsVectorLayerUtils.getValues(augmented_cons_buildings, 'OBJECTID_1')[0]
            hub_ids = QgsVectorLayerUtils.getValues(augmented_cons_buildings, 'HubName')[0]
            hub_dist = QgsVectorLayerUtils.getValues(augmented_cons_buildings, 'HubDist')[0]
            
            return list(zip(ids, hub_ids, hub_dist))
        except:
            ids = QgsVectorLayerUtils.getValues(cons_buildings, 'OBJECTID_1')[0]
            hub_ids = [NULL]*len(ids)
            hub_dist = [NULL]*len(ids)
            
            return list(zip(ids, hub_ids, hub_dist))
    
    if 'MO_DIST' not in [field.name() for field in address_layer.fields()]:
        address_layer.dataProvider().addAttributes([QgsField("MO_DIST",QVariant.Double)])
        address_layer.updateFields()
    if 'MO_ID' not in [field.name() for field in address_layer.fields()]:
        address_layer.dataProvider().addAttributes([QgsField("MO_ID",QVariant.String)])
        address_layer.updateFields()
    if 'MO_DIST' not in [field.name() for field in buildings_layer.fields()]:
        buildings_layer.dataProvider().addAttributes([QgsField("MO_DIST",QVariant.Double)])
        buildings_layer.updateFields()
    if 'MO_ID' not in [field.name() for field in buildings_layer.fields()]:
        buildings_layer.dataProvider().addAttributes([QgsField("MO_ID",QVariant.String)])
        buildings_layer.updateFields()
    
    bldg_centroids = processing.run("native:centroids", {'INPUT':buildings_layer.dataProvider().dataSourceUri(),'ALL_PARTS':False,'OUTPUT':'TEMPORARY_OUTPUT'})['OUTPUT']
    
    obj_id_to_hub_dist_address = dict()
    obj_id_to_hub_dist_building = dict()
    
    for cons in cons_to_dev_dict.keys():
        for item in compute_address_distances(cons):
            obj_id_to_hub_dist_address[item[0]] = (item[1], item[2])
        for item in compute_building_distances(cons, bldg_centroids):
            obj_id_to_hub_dist_building[item[0]] = (item[1], item[2])
        
            
    with edit(address_layer):
        for feature in address_layer.getFeatures():
            feature.setAttribute('MO_ID', obj_id_to_hub_dist_address[feature['OBJECTID']][0])
            feature.setAttribute('MO_DIST', obj_id_to_hub_dist_address[feature['OBJECTID']][1])
            address_layer.updateFeature(feature)
            
    with edit(buildings_layer):
        for feature in buildings_layer.getFeatures():
            feature.setAttribute('MO_ID', obj_id_to_hub_dist_building[feature['OBJECTID_1']][0])
            feature.setAttribute('MO_DIST', obj_id_to_hub_dist_building[feature['OBJECTID_1']][1])
            buildings_layer.updateFeature(feature)
                

#--------------------------------------------------------------------------
cons_to_dev, dev_to_cons = get_consolidation_crosswalk(buildings_layer=blayer, tds_att='TDS_NUM', cons_tds_att='CONS_TDS')
enrich_addresses(dev_to_cons_dict=dev_to_cons)
enrich_buildings(alayer, blayer)
compute_distances(cons_to_dev)

