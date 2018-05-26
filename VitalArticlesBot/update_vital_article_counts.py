#!/usr/bin/env python3
from __future__ import absolute_import, unicode_literals
from itertools import groupby
import mwparserfromhell
import re

import pywikibot
from pywikibot import pagegenerators

from pywikibot.bot import (
    SingleSiteBot, ExistingPageBot, NoRedirectPageBot, AutomaticTWSummaryBot)
from pywikibot.tools import issue_deprecation_warning

"""
Bot script to update the article counts and assessments at [[Wikipedia:Vital articles]]

The following parameters are supported:

&params;

-always           The bot won't ask for confirmation when putting a page

-text:            Use this text to be added; otherwise 'Test' is used

-replace:         Dont add text but replace it

-top              Place additional text on top of the page

-summary:         Set the action summary message for the edit.
"""
#
# (C) Pywikibot team, 2006-2018
# (C) Richard Jenkins (firefly) 2018
#
# Distributed under the terms of the MIT license.
#

# This is required for the text that is shown when you run this script
# with the parameter -help.
docuReplacements = {
    '&params;': pagegenerators.parameterHelp
}


class FireflyBot(
    SingleSiteBot,  # A bot only working on one site
    ExistingPageBot,  # CurrentPageBot which only treats existing pages
    NoRedirectPageBot,  # CurrentPageBot which only treats non-redirects
):
    def __init__(self, generator, **kwargs):
        """
        Constructor.

        @param generator: the page generator that determines on which pages
            to work
        @type generator: generator
        """
        # Add your own options to the bot and set their defaults
        # -always option is predefined by BaseBot class
        self.availableOptions.update({
            'replace': False,  # delete old text and write the new text
            'summary': None,  # your own bot summary
            'text': 'Test',  # add this text from option. 'Test' is default
            'top': False,  # append text on top of the page
        })

        # call constructor of the super class
        super(FireflyBot, self).__init__(site=True, **kwargs)

        # handle old -dry parameter
        self._handle_dry_param(**kwargs)

        # assign the generator to the bot
        self.generator = generator

    def _handle_dry_param(self, **kwargs):
        """
        Read the dry parameter and set the simulate variable instead.

        This is a private method. It prints a deprecation warning for old
        -dry paramter and sets the global simulate variable and informs
        the user about this setting.

        The constuctor of the super class ignores it because it is not
        part of self.availableOptions.

        @note: You should ommit this method in your own application.

        @keyword dry: deprecated option to prevent changes on live wiki.
            Use -simulate instead.
        @type dry: bool
        """
        if 'dry' in kwargs:
            issue_deprecation_warning('dry argument',
                                      'pywikibot.config.simulate', 1)
            # use simulate variable instead
            pywikibot.config.simulate = True
            pywikibot.output('config.simulate was set to True')

    def treat_page(self):
        pass

class VitalArticlesBot(FireflyBot):

    assessment_order = ["fa", "fl", "a", "ga", "bplus", "b", "c", "start", "stub", "dab", "list", "unassessed"]
    
    no_replace_list = ["dga", "ffa", "ffac"]

    # Gets the article's assessment. If the page has multiple different assessments
    # then the HIGHEST assessment is used
    def get_vital_article_quality(self, page_title):

        def sanitise_assessment(ass):  # Hehehe 'ass'. I'm a serious programmer.
            ass = ass.lower()
            return ass.split("<!")[0].strip()  # Gets rid of <!-- HTML comments -->

        assessments = []
        article_page = pywikibot.Page(self.site, page_title)
        
         # Pesky redirects
        if article_page.isRedirectPage():
            talk_page = pywikibot.Page(self.site, "Talk:{}".format(article_page.getRedirectTarget().title()))
        else:
            talk_page = pywikibot.Page(self.site, "Talk:{}".format(page_title))
        
        talk_wikicode = mwparserfromhell.parse(talk_page.text)
        
        for template in talk_wikicode.filter_templates():
            template_name_lower = template.name.lower()
            try:
                assessment = sanitise_assessment(template.get("class").split("=")[1])
                if assessment in self.assessment_order:  # Reject invalid assessment classes (e.g. if someone has vandalised the template)
                    assessments.append(assessment)
            except ValueError:  # The WikiProject template may not have an assessment parameter
                continue  # Skip to the next one

        if len(assessments) == 0:
            if "WikiProject Disambiguation" in talk_page.text:
                return "dab"
            else:
                return "unassessed"
        elif len(assessments) > 1:
            assessments.sort(key=lambda x: self.assessment_order.index(x) if x in self.assessment_order else 255)
        return assessments[0]

    # The relevant article will be the first link in a line
    @staticmethod
    def get_article_link(line):
        for item in line:
            if "[[" in item:
                bare_name = str(item).strip("[]'")
                if "|" in bare_name:
                    return bare_name.split("|")[0]
                else:
                    return bare_name

    def treat_page(self):
        # Grab the page text and parse it
        text = self.current_page.text
        wikicode = mwparserfromhell.parse(text, skip_style_tags=True)

        # Count the articles in each section and update the header accordingly
        for section in wikicode.get_sections(include_lead=False):
            article_count = section.count("\n#")
            old_header_match = re.match(r"(=+)\s*(.+?)\s*\(([0-9,]+) articles?\)\s*=+", str(section))
            old_header_groups = old_header_match.groups()
            new_header = "{0}{1} ({2} article{3}){0}".format(old_header_groups[0],
                                                                old_header_groups[1],
                                                                article_count,
                                                                "" if article_count == 1 else "s")

            section.replace(old_header_match.group(0), new_header)

        # Add all the top-level headings together for the 'total articles' count
        total_count = 0
        for i in range(1,10):
            top_level_sections = wikicode.get_sections(levels=[i])
            if len(top_level_sections) > 0:
                for section in top_level_sections:
                    heading = str(section.filter_headings()[0])
                    heading_match = re.search(r"\(([0-9]+) articles?\)", heading)
                    total_count += int(heading_match.group(1))
                break

        # Update the 'total articles' count
        for template in wikicode.filter_templates():
            if template.name.matches("huge"):
                template.add("1", "Total articles: {}".format(total_count))

        # Split article into individual lines
        line_list = [list(group) for k, group in groupby(wikicode.filter(), lambda x: "\n" in x) if not k]

        # Process each line, looking for article links, then check their assessment
        for line in line_list:
            if line[0] == "#":
                article_assessment = self.get_vital_article_quality(self.get_article_link(line))
                print("Getting assessment for {}: {}".format(self.get_article_link(line), article_assessment))
                for item in line:
                    if "{{" in item:
                        existing_assessment = item.get("1").lower()
                        if existing_assessment != article_assessment and existing_assessment not in self.no_replace_list:  # Don't just change capitalisation, don't replace DGA or FFA
                            item.add("1", article_assessment)
                        if (existing_assessment == "dga" and article_assessment == "ga") or \
                            (existing_assessment == "ffa" and article_assessment == "fa"):  # Remove DGA template if article is now a GA / FFA if FA
                            wikicode.remove(item)

        # Save the updated text to the page
        self.put_current(str(wikicode),
                            summary="(TEST) Updating section counts and WikiProject assessments")

def main(*args):
    """
    Process command line arguments and invoke bot.

    If args is an empty list, sys.argv is used.

    @param args: command line arguments
    @type args: list of unicode
    """
    options = {}
    # Process global arguments to determine desired site
    local_args = pywikibot.handle_args(args)

    # This factory is responsible for processing command line arguments
    # that are also used by other scripts and that determine on which pages
    # to work on.
    genFactory = pagegenerators.GeneratorFactory()

    # Parse command line arguments
    for arg in local_args:

        # Catch the pagegenerators options
        if genFactory.handleArg(arg):
            continue  # nothing to do here

        # Now pick up your own options
        arg, sep, value = arg.partition(':')
        option = arg[1:]
        if option in ('summary', 'text'):
            if not value:
                pywikibot.input('Please enter a value for ' + arg)
            options[option] = value
        # take the remaining options as booleans.
        # You will get a hint if they aren't pre-defined in your bot class
        else:
            options[option] = True

    # The preloading option is responsible for downloading multiple
    # pages from the wiki simultaneously.
    gen = genFactory.getCombinedGenerator(preload=True)
    if gen:
        # pass generator and private options to the bot
        bot = VitalArticlesBot(gen, **options)
        bot.run()  # guess what it does
        return True
    else:
        pywikibot.bot.suggest_help(missing_generator=True)
        return False


if __name__ == '__main__':
    main()
