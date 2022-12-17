import os
from configparser import ConfigParser

from backports import configparser
from bs4 import BeautifulSoup
import pandas as pd
import sqlalchemy as db
from fuzzywuzzy import fuzz

config_path = 'config.ini'
config = configparser.ConfigParser()


def read_mimosa_xml(engine):
    id_number = 1
    name_list = []
    description_list = []
    relationship_list = []
    id_list = []

    # Opens MIMOSA standards file to extract concept data - this must be a xsd/xml file to work correctly.
    with open("standards_files/mimosa_standards.xsd") as fp:
        soup = BeautifulSoup(fp, "xml")

    # Concepts are listed under complexType name: in xml files
    for concept_name in soup.find_all("complexType", {'name': True}):
        if concept_name is not None:
            name_list.append(concept_name['name'])

    name_list = list(dict.fromkeys(name_list))

    for stored_name in name_list:
        for complex_type in soup.find_all('xs:complexType', {'name': stored_name}):
            complex_description = complex_type.find('xs:documentation')
            if complex_description is not None:
                description_text = complex_description.get_text()
                description_list.append(description_text)
            else:
                # Concepts that do not have a description will be given a N/A description to keep list size consistent.
                description_list.append('N/A')

        # Grabs list length to append a unique ID to each concept
        list_length = len(name_list)
        for complex_type in soup.find_all('xs:complexType', {'name': stored_name}):
            relationships = [tag['type'] for tag in complex_type.find_all("xs:element", {'type': True})]
            if not relationships:
                relationship_list.append(['N/A'])
            else:
                relationship_list.append(relationships)

        # Cleans list containing only brackets
        relationship_list = [brackets for brackets in relationship_list if brackets != []]

        while id_number <= list_length:
            id_list.append(id_number)
            id_number += 1

    # Writes list to dataframe and stores in sql for easy retrieval of standard data including relationships, description.
    mimosa_list = {'idMimosa': id_list, 'name': name_list, 'description': description_list, 'relationships': relationship_list}
    mimosa_df = pd.DataFrame(mimosa_list)
    # Separates words in relationship column by comma for matching purposes
    mimosa_df['relationships'] = mimosa_df['relationships'].str.join(', ')
    mimosa_df.to_sql('mimosa', con=engine, if_exists='replace', chunksize=1000, index=False)
    print('----MIMOSA table created----')

    return mimosa_df


def read_plcs_xml(engine):
    id_number = 1
    id_list = []
    name_list = []
    description_list = []
    relationship_list = []

    # Opens PLCS standards file to extract concept data - this must be a xsd/xml file to work correctly.
    with open("standards_files/plcs_standards.xsd") as fp:
        soup = BeautifulSoup(fp, "xml")

    # Concepts are listed under complexType name: in xml files
    for concept_name in soup.find_all("complexType", {'name': True}):
        if concept_name is not None:
            name_list.append(concept_name['name'])

    name_list = list(dict.fromkeys(name_list))

    for stored_name in name_list:
        # Grabs list length to append a unique ID to each concept
        list_length = len(name_list)
        for complex_type in soup.find_all('xsd:complexType', {'name': stored_name}):
            complex_description = complex_type.find('xsd:documentation')
            if complex_description is not None:
                description_text = complex_description.get_text()
                description_list.append(description_text)
            else:
                # Concepts that do not have a description will be given a N/A description to keep list size consistent.
                description_list.append('N/A')

        for complex_type in soup.find_all('xsd:complexType', {'name': stored_name}):
            relationships = [tag['type'] for tag in complex_type.find_all("xsd:element", {'type': True})]
            if not relationships:
                relationship_list.append(['N/A'])
            else:
                relationship_list.append(relationships)

            # Cleans list containing only brackets
            relationship_list = [brackets for brackets in relationship_list if brackets != []]

        while id_number <= list_length:
            id_list.append(id_number)
            id_number += 1

    # Writes list to dataframe and stores in sql for easy retrieval of standard data including relationships, description.
    plcs_list = {'idPLCS': id_list, 'name_plcs': name_list, 'description': description_list, 'relationships': relationship_list}
    plcs_df = pd.DataFrame(plcs_list)
    # Separates words in relationship column by comma for matching purposes
    plcs_df['relationships'] = plcs_df['relationships'].str.join(', ')
    plcs_df.to_sql('plcs', con=engine, if_exists='replace', chunksize=1000, index=False)
    print('----PLCS table created----')

    return plcs_df


def connect_to_db():
    meta = db.MetaData()
    config.read(config_path)
    config_object = dict(config.items('SQLSERVERCONFIG'))
    user_info = config_object
    engine = db.create_engine("mysql+pymysql://{user}:{pw}@localhost/{db}"
                           .format(user=format(user_info["user"]),
                                   pw=format(user_info["password"]),
                                   db=format(user_info["database"])))
    print('----Connected to DB----')

    db.Table(
        'mimosa',
        meta,
        db.Column('id_mimosa', db.Integer, primary_key=True),
        db.Column('name', db.String(256)),
        db.Column('description', db.String(5000)),
        db.Column('relationships', db.String(5000)),
    )

    db.Table(
        'plcs',
        meta,
        db.Column('id_plcs', db.Integer, primary_key=True),
        db.Column('name', db.String(256)),
        db.Column('description', db.String(5000)),
        db.Column('relationships', db.String(5000)),
    )

    db.Table(
        'similarity',
        meta,
        db.Column('id_sim', db.Integer, primary_key=True),
        db.Column('name_plcs', db.String(256)),
        db.Column('name_mimosa', db.String(256)),
        db.Column('sim_name', db.Integer),
        db.Column('sim_description', db.Integer),
        db.Column('sim_relationship', db.Integer),
    )

    meta.create_all(engine)
    print("----Tables were successfully created----")

    return engine


def name_match(mimosa_df, plcs_df):
    threshold = 0
    mimosa_list = []
    plcs_list = []
    similarity_score_list = []
    id_list = []
    unique_id = 0

    plcs_name_list = plcs_df['name_plcs'].values.tolist()
    mimosa_name_list = mimosa_df['name'].values.tolist()
    for name_plcs in plcs_name_list:
        for name_mimosa in mimosa_name_list:
            # Fuzzy token_set_ratio used for name matches as it provides most accurate comparison
            similarity_score = fuzz.token_set_ratio(name_mimosa, name_plcs)
            if similarity_score >= threshold:
                mimosa_list.append(name_mimosa)
                plcs_list.append(name_plcs)
                similarity_score_list.append(similarity_score)
                unique_id += 1
                id_list.append(unique_id)

    similarity_list = {'id_sim': id_list, 'name_plcs': plcs_list, 'name_mimosa': mimosa_list, 'sim_name': similarity_score_list}
    similarity_df = pd.DataFrame(similarity_list)
    ("----Name Matching Complete and Stored----")

    return similarity_df


def description_matching(mimosa_df, plcs_df, df):
    similarity_description = []
    plcs_list = plcs_df['description'].values.tolist()
    mimosa_list = mimosa_df['description'].values.tolist()

    for description_plcs in plcs_list:
        for description_mimosa in mimosa_list:
            if description_mimosa == 'N/A':
                similarity_description.append(0)
            else:
                similarity = fuzz.ratio(description_mimosa, description_plcs)
                similarity_description.append(similarity)

    similarity_df = df.assign(sim_description=similarity_description)
    print("----Description Matching Complete and Stored----")

    return similarity_df


def relationship_matching(mimosa_df, plcs_df, similarity_df):
    similarity_relationships = []
    plcs_list = plcs_df['relationships'].values.tolist()
    mimosa_list = mimosa_df['relationships'].values.tolist()
    plcs_list = [w.replace('N/A', '') for w in plcs_list]
    mimosa_list = [w.replace('N/A', '') for w in mimosa_list]

    for relationship_plcs in plcs_list:
        for relationship_mimosa in mimosa_list:
            similarity = fuzz.token_set_ratio(relationship_mimosa, relationship_plcs)
            similarity_relationships.append(similarity)

    similarity_df = similarity_df.assign(sim_relationships=similarity_relationships)
    similarity_df.to_sql('similarity', con=engine, if_exists='replace', chunksize=1000, index=False)
    print("----Relationship Matching Complete and Stored----")

    return similarity_df


def create_config():
    if not os.path.exists(config_path):
        config["THRESHOLDANDWEIGHTING"] = {
            "Threshold": "40",
            "Name Weighting": "65",
            "Description Weighting": "23",
            "Relationship Weighting": "12"
        }

        config["SQLSERVERCONFIG"] = {
            "User": "root",
            "Password": "password",
            "Host": "localhost",
            "Database": "automatedmatching"
        }

        with open('config.ini', 'w') as conf:
            config.write(conf)
        print('Created config file')
    else:
        print('Skipped creation of config file')

def weighting(similarity_df):
    user_info = config["THRESHOLDANDWEIGHTING"]
    name_weighting = float(user_info["name weighting"])
    description_weighting = float(user_info["description weighting"])
    relationship_weighting = float(user_info["relationship weighting"])
    threshold = float(user_info["threshold"])

    # Applies weighting to the original fuzzywuzzy scores, must be == 100 for accurate matches
    similarity_df["weighted_similarity"] = similarity_df["sim_name"] * name_weighting / 100 + similarity_df["sim_description"] \
                                           * description_weighting / 100 + similarity_df["sim_relationships"] * \
                                           relationship_weighting /100
    similarity_df = similarity_df[similarity_df.weighted_similarity >= threshold]

    similarity_df.to_sql('similarity', con=engine, if_exists='replace', chunksize=1000, index=False)


create_config()
engine = connect_to_db()
mimosa_df = read_mimosa_xml(engine)
plcs_df = read_plcs_xml(engine)
similarity_df = name_match(mimosa_df, plcs_df)
similarity_df = description_matching(mimosa_df, plcs_df, similarity_df)
similarity_df = relationship_matching(mimosa_df, plcs_df, similarity_df)
weighting(similarity_df)
