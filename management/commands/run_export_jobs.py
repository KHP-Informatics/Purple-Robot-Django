import datetime
import gzip
import json
import pytz
import tempfile
import urllib
import urllib2

from django.contrib.sites.models import Site
from django.core.files import File
from django.core.files.base import ContentFile
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.template import Context
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.crypto import get_random_string

from purple_robot.settings import ADMINS, URL_PREFIX
from purple_robot_app.models import *

class Command(BaseCommand):
    def handle(self, *args, **options):
        processing = PurpleRobotExportJob.objects.filter(state='processing')
        pending = PurpleRobotExportJob.objects.filter(state='pending')
        
        if processing.count() > 0:
            pass # Do nothing - already compiling a job...
        elif pending.count() < 1:
            pass # No work to do...
        else:
            job = pending.order_by('pk')[0]
            
            job.state = 'processing'
            job.save()
            
            hashes = job.users.split()
            probes = job.probes.split()
            
            start = datetime.datetime(job.start_date.year, job.start_date.month, job.start_date.day, 0, 0, 0, 0) 
            end = datetime.datetime(job.end_date.year, job.end_date.month, job.end_date.day, 23, 59, 59, 999999) 
            
            q_probes = None

            temp_file = tempfile.TemporaryFile()

            gzf = gzip.GzipFile(mode='wb', fileobj=temp_file)
            gzf.write('User ID\tProbe\tLogged\tPayload\n')
            
            for probe in probes:
                if q_probes == None:
                    q_probes = Q(probe=probe)
                else:
                    q_probes = (q_probes | Q(probe=probe))
                    
            for hash in hashes:
                readings = None
                
                if q_probes != None:
                    readings = PurpleRobotReading.objects.filter(q_probes, user_id=hash, logged__gte=start, logged__lte=end).order_by('logged')
                else:
                    readings = PurpleRobotReading.objects.filter(user_id=hash, logged__gte=start, logged__lte=end).order_by('logged')
                    
                for reading in readings:
                    payload = json.loads(reading.payload)
                    
                    gzf.write(hash + '\t' + reading.probe + '\t' + str(reading.logged) + '\t' + json.dumps(payload) + '\n')
                    
            gzf.flush()
            gzf.close()
                
            temp_file.seek(0)
            
            job.export_file.save('export_' + job.start_date.isoformat() + '_' + job.end_date.isoformat() + '_' + get_random_string(16).lower() + '.txt.gz', File(temp_file))
            job.state = 'finished'
            job.save()
            
            if job.destination != None and job.destination != '':
                c = Context()
                c['job'] = job
                c['prefix'] = URL_PREFIX

                message = render_to_string('export_email.txt', c)
                
                send_mail('Your Purple Robot data is available', message, 'Purple Robot <' + ADMINS[0][1] + '>', [job.destination], fail_silently=False)
