#!/usr/bin/env python2.6
'''Generates the docs for CMS DB Web services.
'''

__author__ = 'Miguel Ojeda'
__copyright__ = 'Copyright 2012, CERN CMS'
__credits__ = ['Miguel Ojeda', 'Andreas Pfeiffer']
__license__ = 'Unknown'
__maintainer__ = 'Miguel Ojeda'
__email__ = 'mojedasa@cern.ch'


if __name__ == '__main__':
    import sys
    if '--productionLevel' not in sys.argv:
        sys.path.insert(0, '/data/services/keeper')
        import keeper
        keeper.run('docs', sys.argv[0], replaceProcess = True)


import os
import re
import logging

import mako.template
import markdown


defaultOutputDirectory = 'generated'
indexFilename = 'index.html'

indexTitle = 'CMS DB Web Services'

docsTemplate = mako.template.Template('''
    <!DOCTYPE html>
    <html>
        <head>
            <title>${title}</title>
            <style>
                body {
	                font-size: 95%;
                }

                h2 {
	                margin-top: 30px;
                }

                pre {
	                margin-left: 60px;
	                margin-bottom: 25px;

	                padding: 10px;
	                border-left: 3px solid;
	                border-top: 1px solid;
	                border-top-left-radius: 10px;
	                background-color: #DFDFDF;
                }
            </style>
        </head>
        <body>${body}</body>
    </html>
''')


# In order to print the list of services we need to exceptionally access the keeper's config
import sys
sys.path.append('../keeper')
import config


def read(filename):
    '''Read stripped data from file.
    '''

    with open(filename, 'rb') as f:
        return f.read().strip()


def write(filename, data):
    '''Write data to a file.
    '''

    with open(filename, 'wb') as f:
        f.write(data)


def main():
    options = {
        'outputDirectory': defaultOutputDirectory,
    }

    # Generate all the docs
    mdwn = markdown.Markdown(safe_mode = 'escape', extensions = ['headerid'])

    documentsList = ''
    inputFilenameRE = re.compile('^(.*)\.mdwn$')
    titleRE = re.compile('^# (.*)$', re.MULTILINE)
    sectionsRE = re.compile('^<h2 id="(.*)">(.*)</h2>$', re.MULTILINE)

    for inputFilename in sorted(os.listdir('.')):
        match = inputFilenameRE.match(inputFilename)
        if not match:
            continue

        outputName = match.groups()[0]
        outputFilename = os.path.join(options['outputDirectory'], outputName + '.html')

        logging.info('Generating: ' + outputFilename + ' from ' + inputFilename)

        fd = open(inputFilename, 'r')
        inputText = fd.read()
        fd.close()

        # If there is a line starting with # (i.e. <h1>), use it as the title.
        # Otherwise default to the outputName.
        title = outputName
        match = titleRE.search(inputText)
        if match:
            title = match.groups()[0]

        bodyText = mdwn.convert(inputText)

        # Search for sections (i.e. ##, <h2>) and build the index with them.
        # This is done after convert() because the headerid extension generates IDs for us automatically.
        index = None
        match = sectionsRE.search(bodyText)
        if match:
            index = '<h2>Index</h2><ol>'
            for section in sectionsRE.findall(bodyText):
                index += '<li><a href="#%s">%s</a></li>' % section
            index += '</ol>'

            # Put the index just before the first section
            # (so that the "abstract" or "introduction" is kept
            # after the title but before the index)
            firstSection = bodyText.find('<h2')
            bodyText = bodyText[:firstSection] + index + bodyText[firstSection:]

        outputText = docsTemplate.render(title = title, body = bodyText)

        write(outputFilename, outputText)

        # Add the doc to the global index
        documentsList += '<li><a href="%s">%s</a></li>' % (outputName + '.html', title)

    # Generate a simple docs' index (i.e. a list of the files)
    outputFilename = os.path.join(options['outputDirectory'], indexFilename)
    logging.info('Generating: ' + outputFilename)

    developmentMailingList = read('developmentMailingList.txt')
    gitWeb = read('gitWeb.txt')
    jiraWeb = read('jiraWeb.txt')

    servicesList = ''
    for service in config.getServicesList():
        servicesList += '<li><a href="/%s/">%s</a></li>' % (service, service)

    bodyText = '''
        <h1>%s</h1>
        <p>Services:</p><ul>%s</ul>
        <p>Development mailing list (you need to be subscribed):</p><ul><li><a href="mailto:%s">%s</a></li></ul>
        <p>Git web:</p><ul><li><a href="%s">%s</a></li></ul>
        <p>JIRA web:</p><ul><li><a href="%s">%s</a></li></ul>
        <p>Documents:</p><ul>%s</ul>
        <p>If it is your first time, please start by reading Developing.</p>
    ''' % (indexTitle, servicesList, developmentMailingList, developmentMailingList, gitWeb, gitWeb, jiraWeb, jiraWeb, documentsList)

    outputText = docsTemplate.render(title = indexTitle, body = bodyText)
    write(outputFilename, outputText)


if __name__ == '__main__':
    logging.basicConfig(
            format = '[%(asctime)s] %(levelname)s: %(message)s',
            level = logging.INFO
    )

    main()

