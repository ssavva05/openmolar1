#! /usr/bin/env python
# -*- coding: utf-8 -*-

# ############################################################################ #
# #                                                                          # #
# # Copyright (c) 2009-2014 Neil Wallace <neil@openmolar.com>                # #
# #                                                                          # #
# # This file is part of OpenMolar.                                          # #
# #                                                                          # #
# # OpenMolar is free software: you can redistribute it and/or modify        # #
# # it under the terms of the GNU General Public License as published by     # #
# # the Free Software Foundation, either version 3 of the License, or        # #
# # (at your option) any later version.                                      # #
# #                                                                          # #
# # OpenMolar is distributed in the hope that it will be useful,             # #
# # but WITHOUT ANY WARRANTY; without even the implied warranty of           # #
# # MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the            # #
# # GNU General Public License for more details.                             # #
# #                                                                          # #
# # You should have received a copy of the GNU General Public License        # #
# # along with OpenMolar.  If not, see <http://www.gnu.org/licenses/>.       # #
# #                                                                          # #
# ############################################################################ #

import logging
import os
import re
import shutil

from collections import namedtuple

from openmolar import connect
from openmolar.settings import localsettings

LOGGER = logging.getLogger("openmolar")


def FEESCALE_DIR():
    '''
    this is dynamic in case user switches database
    '''
    return os.path.join(
        localsettings.localFileDirectory,
        "feescales",
        connect.params.database_name.replace(" ", "_").replace(":", "_PORT_")
    )


def write_readme():
    dir_path = FEESCALE_DIR()
    LOGGER.info("creating directory %s" % dir_path)
    os.makedirs(dir_path)
    f = open(os.path.join(dir_path, "README.txt"), "w")
    f.write('''
This folder is created by openmolar to store xml copies of the feescales in
database %s.
Filenames herein are IMPORTANT!
feescale1.xml relates to the xml stored in row 1 of that table
feescale2.xml relates to the xml stored in row 2 of that table

whilst you are free to edit these files using an editor of your choice,
validation against feescale_schema.xsd is highly recommended.

note - openmolar has a build in application for doing this.

in addition - why not use some version control for this folder?
    ''' % connect.params.database_name)
    f.close()


QUERY = 'select ix, xml_data from feescales'

SPECIFIC_QUERY = 'select xml_data from feescales where ix=%s'

UPDATE_QUERY = "update feescales set xml_data = %s where ix = %s"

NEW_FEESCALE_QUERY = "insert into feescales (xml_data) values(%s)"


def get_digits(string_value):
    '''
    used as a key for sort function for filenames.
    I want foo_10 to be after foo_9 etc..
    '''
    m = re.search("(\d+)", string_value)
    if not m:
        return None
    return int(m.groups()[0])


class FeescaleHandler(object):
    ixs_in_db = set([])

    def get_feescale_from_database(self, ix):
        '''
        connects and gets the xml_data associated with ix
        '''
        db = connect.connect()
        cursor = db.cursor()
        cursor.execute(SPECIFIC_QUERY, (ix,))
        row = cursor.fetchone()
        cursor.close()
        if row:
            return row[0]
        return ""

    def get_feescales_from_database(self,
                                    in_use_only=True, priority_order=True):
        '''
        connects and get the data from feetable_key
        '''
        query = QUERY
        if in_use_only:
            query += ' where in_use = True'
        else:  # if called by feescale editor
            self.ixs_in_db = set([])
        if priority_order:
            query += ' order by priority desc'
        db = connect.connect()
        cursor = db.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
        LOGGER.debug("%d feescales retrieved" % len(rows))
        for ix, xml_data in rows:
            self.ixs_in_db.add(ix)
        return rows

    def save_file(self, ix, xml_data):
        file_path = self.index_to_local_filepath(ix)
        LOGGER.debug("writing %s" % file_path)
        f = open(file_path, "w")
        f.write(xml_data)
        f.close()

    def _xml_data_and_filepaths(self):
        for ix, xml_data in self.get_feescales_from_database(False):
            xml_file = namedtuple("XmlFile", ("data", "filepath"))
            xml_file.data = xml_data
            xml_file.filepath = self.index_to_local_filepath(ix)

            yield xml_file

    def non_existant_and_modified_local_files(self):
        '''
        returns 2 lists
        [local files which have been created]
        [local files which differ from stored data]
        '''
        unwritten, modified = [], []
        for xml_file in self._xml_data_and_filepaths():
            if not os.path.isfile(xml_file.filepath):
                unwritten.append(xml_file)
            else:
                f = open(xml_file.filepath, "r")
                if f.read().strip() != xml_file.data.strip():
                    modified.append(xml_file)
                f.close()
        return unwritten, modified

    def index_to_local_filepath(self, ix):
        return os.path.join(FEESCALE_DIR(), "feescale_%d.xml" % ix)

    def check_dir(self):
        if not os.path.exists(FEESCALE_DIR()):
            write_readme()

    @property
    def local_files(self):
        self.check_dir()
        dirname = FEESCALE_DIR()
        for file_ in sorted(os.listdir(dirname), key=get_digits):
            m = re.match("feescale_(\d+)\.xml$", file_)
            if m:
                ix = int(m.groups()[0])
                yield ix, os.path.join(dirname, file_)

    def temp_move(self, file_ix):
        '''
        after insert, a local file may need to move.
        this is done cautiously as could overwrite another
        '''
        path = self.index_to_local_filepath(file_ix)
        shutil.move(path, path + "temp")

    def final_move(self, file_ix, db_ix):
        '''
        finalised temp_move
        '''
        temp_path = self.index_to_local_filepath(file_ix) + "temp"
        final_path = self.index_to_local_filepath(db_ix)
        shutil.move(temp_path, final_path)

    def update_db_all(self):
        '''
        apply all local file changes to the database.
        '''
        message = ""
        insert_ids = []
        for ix, filepath in self.local_files:
            if ix in self.ixs_in_db:
                message += self.update_db(ix)
            else:
                insert_ids.append(ix)
        return message, insert_ids

    def update_db(self, ix):
        message = ""
        filepath = self.index_to_local_filepath(ix)
        LOGGER.debug("updating database ix %s" % ix)
        if not os.path.isfile(filepath):
            message = "FATAL %s does not exist!" % filepath
        else:
            db = connect.connect()
            cursor = db.cursor()

            f = open(filepath)
            data = f.read()
            f.close()

            values = (data, ix)
            result = cursor.execute(UPDATE_QUERY, values)

            r_message = "commiting feescale '%s' to database." % filepath
            message = "updating feescale %d    result = %s\n" % (
                ix, "OK" if result else "No Change applied")

            db.close()
            LOGGER.info(r_message + " " + message)

        return message

    def insert_db(self, ix):
        message = ""
        filepath = self.index_to_local_filepath(ix)
        LOGGER.debug("inserting new feescale into database %s" % ix)
        if not os.path.isfile(filepath):
            message = "FATAL %s does not exist!" % filepath
        else:
            db = connect.connect()
            cursor = db.cursor()

            f = open(filepath)
            data = f.read()
            f.close()

            values = (data,)
            cursor.execute(NEW_FEESCALE_QUERY, values)
            db_ix = db.insert_id()
            self.ixs_in_db.add(db_ix)

            r_message = "inserting new feescale '%s' to database." % filepath
            db.close()

            LOGGER.info(r_message)
            return db_ix

    def save_xml(self, ix, xml):
        file_path = self.index_to_local_filepath(ix)
        LOGGER.info("saving %s" % file_path)

        LOGGER.debug("creating backup")
        try:
            shutil.copy(file_path, file_path + "~")
        except IOError:
            LOGGER.warning("no backup file created")

        f = open(file_path, "w")
        f.write(xml)
        f.close()
        return True


feescale_handler = FeescaleHandler()

if __name__ == "__main__":
    logging.basicConfig()
    LOGGER.setLevel(logging.DEBUG)

    fh = FeescaleHandler()
    fh.get_feescales_from_database()
    for ix, local_file in fh.local_files:
        print ix, local_file
    print fh.non_existant_and_modified_local_files()
