# coding=utf-8
from multiprocessing import Pool
from GlobalTagCollector.libs import utils
from GlobalTagCollector.libs.GTManagement import RawGT
from GlobalTagCollector.libs.data_inserters import AccountObjectCreator, TagObjectCreator
from GlobalTagCollector.libs.data_inserters import RecordObjectCreator, SoftwareReleaseCreator
from GlobalTagCollector.models import Account, HardwareArchitecture, GTQueue, AccountType, GTAccount, GTType, ObjectForRecords, Record, SoftwareRelease, GlobalTag
from data_providers import *
from data_filters import AccountFilter, TagsFilter, RecordsFilter, SoftwareReleaseFilter, GlobalTagListFilter, HardwareArchitecturesFilter
from GlobalTagCollector.libs.data_patchers import PatchTagContainers
from data_inserters import  AccountTypeObjectsCreator, GlobalTagQueuePreparer, GTCreatorQueueUpdater #, GlobalTagPreparer
from GlobalTagCollector.libs.data_providers import SchemasProvider, GlobalTagProvider
from django.db.transaction import commit_on_success

import pprint
import logging
import traceback
import sys
import json
from django.contrib.flatpages.models import FlatPage, Site

from django.core.management import call_command
from GlobalTagCollector.models import GTTypeCategory
from GlobalTagCollector.libs.exceptions import DataAccessException, DataFormatException
import pprint

logger = logging.getLogger("print_them_all")

class AccountTypesUpdateManager(object):
    def _run(self):
        try:
            #logger.debug("Starting account types update")
            account_types = DatabasesProvider().provide()

            #logger.debug("Account types got: %s" % str(account_types) )
            account_type_objects = AccountTypeObjectsCreator()._create_objects(account_types)

            #logger.debug("Account Types created: %s" % str(account_type_objects) )
        except Exception as e:
            exception_info = sys.exc_info()
            #logger.error("Account Types update failed. Exception details: %s" %  repr(traceback.format_exception(*exception_info)))

class AccountsUpdateManager(object):

    def _run(self):
        for at in AccountType.objects.all():
            schemas = SchemasProvider()._provide(at.name)
            account_objects = AccountObjectCreator()._create_objects(at, schemas)

#        try:
#            logger.debug("Starting accounts update")
#            accounts = AccountsProvider().provide()
#            logger.debug("Accounts got: %s" % str(accounts) )
#
#            filtered_accounts = AccountFilter().leave_not_existing(accounts)
#            logger.debug("Accounts after filtering: %s" % str(filtered_accounts) )
#
#            account_objects = AccountObjectCreator()._create_objects(filtered_accounts)
#            logger.debug("Accounts created: %s" % str(account_objects) )
#        except Exception as e:
#            exception_info = sys.exc_info()
#            logger.error("Accounts update failed. Exception details: %s" %  repr(traceback.format_exception(*exception_info)))


class TagsUpdateManager(object):

    def _run(self):
        accounts_for_update = Account.objects.filter(use_in_gt_import=True).select_related()
        logger.error("Accounts for update: " + str(accounts_for_update))
        for account in accounts_for_update:
            try:
                logger.info("Updating tags for account %s" % account)

                account_connection_sting = account.account_type.connection_string + account.name
                logger.info("Using connection string %s" % account_connection_sting)

                tags_containers = TagsProvider()._provide(account_connection_sting)

                logger.debug("Tags provided for connection string: %s. %s" % (str(account_connection_sting), str(tags_containers)) )

                patched_tags_containers = PatchTagContainers().patch(account, tags_containers) #todo don't need to patch
                                                                                               #todo need to log

                filtered_tag_containers = TagsFilter().leave_not_existing(account, patched_tags_containers)
                logger.debug("Tags filtered for connection string: %s. %s" % (str(account_connection_sting), str(filtered_tag_containers)) )

                tags_containers_objects = TagObjectCreator()._create_objects(account, filtered_tag_containers)
                logger.debug("Tags created for connection string: %s. %s" % (str(account_connection_sting), str(filtered_tag_containers)) )
            except Exception as e:
                logger.exception(e)
                logger.error("Tags update failed for %s. Exception details %s" % (account_connection_sting, str(e)))


class HardwareArchitecturesUpdateManager(object):

    def _run(self):
        hw_arch_list = HardwareArchitecturesListProvider()._provide()
        filtered_hw_arch_list = HardwareArchitecturesFilter().leave_not_existing(hw_arch_list)
        # Populate db (table GlobalTagCollector_hardwarearchitecture) with filtered hardware architectures
        for hwa in filtered_hw_arch_list:
            HardwareArchitecture.objects.get_or_create(name="%s" % hwa)


class SoftwareReleaseUpdateManager(object):

    def _run(self):
        for hardware_architecture in HardwareArchitecture.objects.all():
            try:
                software_release_names = SoftwareReleaseProvider()._provide(hardware_architecture.name)
                logger.debug("Releases provided for hardware architecture: %s. %s" % (str(hardware_architecture.name), str(software_release_names)) )

                filtered_software_release_names = SoftwareReleaseFilter().leave_not_existing(hardware_architecture, software_release_names)
                logger.debug("Releases filtered for hardware architecture: %s. %s" % (str(hardware_architecture.name), str(filtered_software_release_names)) )

                new_releases = SoftwareReleaseCreator()._create_objects(hardware_architecture,filtered_software_release_names)
                logger.debug("Releases created for hardware architecture: %s. %s" % (str(hardware_architecture.name), str(new_releases)) )
            except Exception as e:
                exception_info = sys.exc_info()
                logger.error("Releases update failed for %s. Exception details %s" % (hardware_architecture.name, str(e)))
                logger.error(traceback.format_exception(*exception_info))
                logger.error(exception_info)


class RecordsFixtureUpdateManager(object):
    ''' Provide and insert correct record-container mapping from a fixture file '''
    def __init__(self):
        self.record_container_list = RecordsFixtureProvider()._provide()

    def _run(self):
        with commit_on_success():
            new_records = []
            for record_name, container_name in self.record_container_list:
                container, container_created = ObjectForRecords.objects.get_or_create(name=container_name)
                record, record_created = Record.objects.get_or_create(name=record_name, object_r=container)
                if record_created:
                    new_records.append(record)
            for software_release in SoftwareRelease.objects.all():
                software_release.record_set.add(*new_records)
                software_release.save()


class RecordsUpdateManager(object):

    def _get_software_releases_for_update(self):
        sofware_realease_dict = {}
        for architecture in HardwareArchitecture.objects.all():
            for release in architecture.softwarerelease_set.all().filter(records_updated=False): #we update only not updated
                sofware_realease_dict[release] = architecture #because we nead only one architecture for release
        return sofware_realease_dict.items() # ( (rel_obj, arch_obj), (rel_obj, arch_obj)..)


    def _run(self):
        software_releases_for_update = self._get_software_releases_for_update()
        #logger.debug("Records will be updated in following software releases: %s" % str(software_releases_for_update) )
        records_filter = RecordsFilter()
        for release, architecture in software_releases_for_update:

            record_container_map = RecordProvider()._provide(architecture_name=architecture.name, release_name=release.name)
            #logger.debug("Records provided for architecture %s, release %s. %s" % (architecture.name, release.name, str(record_container_map)) )

            filtered_record_container_map = records_filter.leave_not_existing(release, record_container_map)
            #logger.debug("Records filtered  release %s. %s" % (release.name, str(record_container_map)) )

            records_created = RecordObjectCreator()._create_objects(release, filtered_record_container_map)
            #logger.debug("Records created  release %s. %s" % (release.name, str(records_created)) )
            release.records_updated = True
            release.save()
            #todo add inseted items to records filter



class GlobalTagsUpdate(object):


    def _get_queue_for_update(self, global_tag_name):
        try:
            return GTQueue.objects.get(expected_gt_name=global_tag_name)
        except GTQueue.DoesNotExist:
            return


    def _process_global_tag(self, global_tag_name):
        #todo details about queue
        logger.info("Importing GT %s" % global_tag_name)
        gt_dict = GlobalTagProvider()._provide(global_tag_name)
        raw_gt = RawGT(gt_dict)
        raw_gt.resolve()
        print global_tag_name, "has errors", raw_gt.has_errors()
        if raw_gt.has_errors(): pprint.pprint(raw_gt.entries_with_errors_dict())
        raw_gt.save()
        logger.info("GT prepared:" + global_tag_name )



#        if not prepared_gt['error_count']:
#            try:
#                queue_for_update = self._get_queue_for_update(global_tag_name)
#              #  import pdb; pdb.set_trace()
#                if queue_for_update:
#                    queue_entries, details = GlobalTagQueuePreparer(queue_for_update, prepared_gt)._prepare_queue_entries()
#                    GTCreatorQueueUpdater()._save(prepared_gt, queue_for_update, queue_entries)
#                else:
#                    logger.info("Saving GT " + global_tag_name)
#                    GTCreatorQueueUpdater()._save(prepared_gt)
#                    logger.info("Saved GT " + global_tag_name)
#                    pass
#            except Exception as e:
#                exception_info = sys.exc_info()
#                utils.update_ignored_global_tags(global_tag_name, repr(traceback.format_exception(*exception_info)))
#                logger.warning("GT import finished with errors followed by exeption:\n%s\nException: %s" % (pprint.pformat(prepared_gt), repr(traceback.format_exception(*exception_info))))
#            else:
#                self._delete_ignored_global_tag(global_tag_name)
#                logger.debug("GT import sucessfull. Details %s" % pprint.pformat(prepared_gt))
#        else:
#            prepared_gt = __reformat_errors(prepared_gt)
#            utils.update_ignored_global_tags(global_tag_name, json.dumps(prepared_gt))
#            logger.warning("GT import finished with errors:\n%s" % pprint.pformat(prepared_gt))

    def _run(self):
        global_tags_list = GlobalTagListProvider()._provide()
        global_tag_names_for_update = GlobalTagListFilter().leave_not_existing(global_tags_list)
        global_tag_names_for_update = list(global_tag_names_for_update)
        global_tag_names_for_update.sort()
        logging.debug("Gobal tags for update:%s" %  str(global_tag_names_for_update))


        gt_names_count = len(global_tag_names_for_update)
        for i, global_tag_name in enumerate(global_tag_names_for_update):
            try:
                logger.info("Processing global tag %d out of %d. Name: %s" % ((i+1), gt_names_count, global_tag_name))
                self._process_global_tag(global_tag_name)
            except (DataAccessException, DataFormatException) as e:
                logger.error("Data is not accessible or has bad format")
                logger.error("exception" + str(e))
                with commit_on_success():
                    gt_obj, created = GlobalTag.objects.get_or_create(name=global_tag_name)
                    if not gt_obj.has_errors:
                        logger.error("Trying to save already correctly saved GT")
                        continue
                    logger.info("Saving problematic GT")
                    error = {"GlobalTag": global_tag_name, "exception":str(e), "exception_class":str(e.__class__)}
                    gt_obj.errors = json.dumps([error], indent=4)
                    gt_obj.save()



class InitialGlobalUpdate(object):

    def update_initial_account_types(self):

        #Updating account types

        arc = AccountType.objects.filter(name='arc').update(
                  visible_for_users = False,
                  title = "Archive",
                  connection_string = "frontier://FrontierArc/",
                  use_in_gt_import  = True,
              )
        integr = AccountType.objects.filter(name='int').update(
                  visible_for_users = True,
                  title = "Offline Integration",
                  connection_string = "frontier://FrontierInt/",
                  use_in_gt_import  = True,
              )
        dev = AccountType.objects.filter(name='dev').update(
                  visible_for_users = True,
                  title = "Offline Preparation",
                  connection_string = "frontier://FrontierPrep/",
                  use_in_gt_import  = True,
              )
        pro = AccountType.objects.filter(name='pro').update(
                  visible_for_users = True,
                  title = "Offline Production",
                  connection_string = "frontier://PromptProd/",
                  use_in_gt_import  = True,
              )

        arc = AccountType.objects.get(name="arc")
        integr = AccountType.objects.get(name="int")
        dev = AccountType.objects.get(name="dev")
        pro = AccountType.objects.get(name="pro")

        # global tag accounts
        global_tag_account, created = GTAccount.objects.get_or_create(pk=1, name="base global tag account")

        #global tag type category
        gttc_arch, created    = GTTypeCategory.objects.get_or_create(pk=1, name="arch")
        gttc_int, created     = GTTypeCategory.objects.get_or_create(pk=2, name="int")
        gttc_mc, created      = GTTypeCategory.objects.get_or_create(pk=3, name="mc")
        gttc_offline, created = GTTypeCategory.objects.get_or_create(pk=4, name="offline")
        gttc_tier0, created   = GTTypeCategory.objects.get_or_create(pk=5, name="tier0")
        gttc_online, created  = GTTypeCategory.objects.get_or_create(pk=6, name="online")

        GTType.objects.get_or_create(pk=1,  account_type=arc, gt_type_category=gttc_arch, type_conn_string="frontier://FrontierArc")

        GTType.objects.get_or_create(pk=2,  account_type=dev,    gt_type_category=gttc_int, type_conn_string="frontier://FrontierPrep")
        GTType.objects.get_or_create(pk=3,  account_type=integr, gt_type_category=gttc_int, type_conn_string="frontier://FrontierInt")

        GTType.objects.get_or_create(pk=4,  account_type=dev,    gt_type_category=gttc_mc, type_conn_string="frontier://FrontierPrep")
        GTType.objects.get_or_create(pk=5,  account_type=integr, gt_type_category=gttc_mc, type_conn_string="frontier://FrontierInt")
        GTType.objects.get_or_create(pk=6,  account_type=pro,    gt_type_category=gttc_mc, type_conn_string="frontier://FrontierProd")

        GTType.objects.get_or_create(pk=7,  account_type=arc, gt_type_category=gttc_mc, type_conn_string="frontier://FrontierArc")

        GTType.objects.get_or_create(pk=8,   account_type=dev,    gt_type_category=gttc_offline, type_conn_string="frontier://FrontierPrep")
        GTType.objects.get_or_create(pk=9,   account_type=integr, gt_type_category=gttc_offline, type_conn_string="frontier://FrontierInt")
        GTType.objects.get_or_create(pk=10,  account_type=pro,    gt_type_category=gttc_offline, type_conn_string="frontier://FrontierProd")

        GTType.objects.get_or_create(pk=11,  account_type=dev,    gt_type_category=gttc_tier0, type_conn_string="frontier://FrontierPrep")
        GTType.objects.get_or_create(pk=12,  account_type=integr, gt_type_category=gttc_tier0, type_conn_string="frontier://FrontierInt")
        GTType.objects.get_or_create(pk=13,  account_type=pro,    gt_type_category=gttc_tier0, type_conn_string="frontier://PromptProd")

        GTType.objects.get_or_create(pk=14,  account_type=pro,    gt_type_category=gttc_online,
            type_conn_string="frontier://(proxyurl=http://localhost:3128)(serverurl=http://localhost:8000/FrontierOnProd)(serverurl=http://localhost:8000/FrontierOnProd)(retrieve-ziplevel=0)(failovertoserver=no)")

        #todo remove if possible
        GTType.objects.get_or_create(pk=15,  account_type=pro,    gt_type_category=gttc_online,
            type_conn_string="frontier://(proxyurl=http://localhost:3128)(serverurl=http://localhost:8000/FrontierOnProd)(serverurl=http://localhost:8000/FrontierOnProd)(serverurl=http://localhost:8000/FrontierOnProd)(retrieve-ziplevel=0)(failovertoserver=no)")

        #todo for replacing
        GTType.objects.get_or_create(pk=16,  account_type=pro,    gt_type_category=gttc_online,
            type_conn_string="frontier://(proxyurl=http://localhost:3128)(serverurl=http://localhost:8000/FrontierOnProd)(serverurl=http://localhost:8000/FrontierOnProd)(retrieve-ziplevel=0)")


        #There are records, where tag and record containers don't match (e.g. payload inspector shows parent container
        # ant recods provider shows child). these values are mapped by adding extra mapping
        #
#        Not matching containers:
        #(tag container, record container). record containers has to be appended
        not_matching_containers = [
            #child                                    #parent
            (u'DTKeyedConfig',                        u'cond::BaseKeyed'),
            (u'PerformancePayloadFromBinnedTFormula', u'PerformancePayload'),
            (u'PerformancePayloadFromTFormula',       u'PerformancePayload'),
            (u'PerformancePayloadFromTable',          u'PerformancePayload'),
            (u'std::vector<unsigned long long>',      u'cond::KeyList')
        ]
        #for tag_container_name, record_container_name in not_matching_containers: #TODO: FIX: BS
        for tag_container_name, record_container_name in not_matching_containers:
#            record_container, created = ObjectForRecords.objects.get_or_create(name=record_container_name)
#            record_container.parent_name = tag_container_name
#            record_container.save()
            tag_container, created = ObjectForRecords.objects.get_or_create(name=tag_container_name)
            tag_container.parent_name = record_container_name
            tag_container.save()

        try:
            flat_page = FlatPage.objects.get(url="/gtc/")
        except FlatPage.DoesNotExist:
            sites = Site.objects.all()
            flat_page = FlatPage(
                url="/gtc/",
                title = 'GTC start page',
                content = 'up and running',
                enable_comments = False,
                registration_required = True,
            )
            flat_page.save()
            for  site in sites:
                flat_page.sites.add(site)
            flat_page.save()

    def _run(self):
        logger.info("Initial global data update: Started")
        AccountTypesUpdateManager()._run()
        self.update_initial_account_types()
        self.initial_data_info()
        HardwareArchitecturesUpdateManager()._run()
        AccountsUpdateManager()._run()
        TagsUpdateManager()._run()
        SoftwareReleaseUpdateManager()._run()
        RecordsFixtureUpdateManager()._run()
        RecordsUpdateManager()._run()
        GlobalTagsUpdate()._run()
        logger.info("Initial global data update: Finished")

    def initial_data_info(self):
        print
        print "=== Account Types ==="
        print
        print "name       | title                          | visible_for_users | connection_string"
        print "_"*106
        for at in AccountType.objects.all():
            print "{name:>10} | {title:>30} | {visible_for_users:>17} | {connection_string:>40}".format(**at.__dict__)


        print
        print "=== Global Tag Type Categories ==="
        print
        print "Name"
        print "_"*10
        for gttc in GTTypeCategory.objects.all():
            print "{name:>10}".format(**gttc.__dict__)


        print
        print "=== Global Tag Types ==="
        print
        print "Account type title   | GT type category | Type connection string"
        print "_"*80

        for gtt in GTType.objects.all():
            print "{account_type:>20} | {gt_type_category:>16} | {type_conn_string}".format(
                        account_type=gtt.account_type,
                        gt_type_category=gtt.gt_type_category,
                        type_conn_string=gtt.type_conn_string,
            )


class GlobalUpdate(object):
    def _run(self):
        logger.info("Global data update: Starting")

        logger.info("HW Architectures update: Starting")
        HardwareArchitecturesUpdateManager()._run()
        logger.info("HW Architectures update: Finished")

        logger.info("Accounts update: Starting")
        AccountsUpdateManager()._run()
        logger.info("Accounts update: Finished")

        logger.info("Tags update: Starting")
        TagsUpdateManager()._run()
        logger.info("Tags update: Finished")

        logger.info("Software release update: Starting")
        SoftwareReleaseUpdateManager()._run()
        logger.info("Software release update: Finished")

        logger.info("Records update: Starting")
        RecordsFixtureUpdateManager()._run()
        RecordsUpdateManager()._run()
        logger.info("Records update: Finished")

        GlobalTagsUpdate()._run()

        logger.info("Global data update: Finished")

#        #RecordsMigration().update_records( )
#        #srm = SoftwareReleaseMigration()
#        #srm.update_software_releases()
