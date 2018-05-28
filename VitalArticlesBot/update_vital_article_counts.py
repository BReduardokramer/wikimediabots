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
        
        self.task_number = -1
        self.check_page = "User:Bot0612/shutoff/{}"

        # call constructor of the super class
        super(FireflyBot, self).__init__(site=True, **kwargs)

        # handle old -dry parameter
        self._handle_dry_param(**kwargs)

        # assign the generator to the bot
        self.generator = generator

    def check_task_switch_is_on(self):
        check_page = pywikibot.Page(self.site, self.check_page.format(self.task_number))
        return (check_page.text.strip() == "active")
        
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
    dga_templates = ["dga", "delistedga"]
    article_history_templates = ["article history", "articlehistory", "articlemilestones", "ah"]
    skip_assessment = False

    def __init__(self, generator, **kwargs):
        self.availableOptions.update({
                'skipassessment': False,
        })

        # call constructor of the super class
        super(VitalArticlesBot, self).__init__(generator, **kwargs)
        self.task_number = 9
        self.skip_assessment = self.options.get("skipassessment")
    
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
        
        is_dga = False
        is_ffa = False
        
        for template in talk_wikicode.filter_templates():
            template_name_lower = template.name.lower()
            
            if template_name_lower in self.dga_templates:
                is_dga = True
            elif template_name_lower in self.article_history_templates:
                try:
                    cur_status = template.get("currentstatus").split("=")[1].strip()
                    is_dga = cur_status.lower() == "dga"
                    is_ffa = cur_status.lower() == "ffa"
                except ValueError:
                    pass
                continue
            
            try:
                assessment = sanitise_assessment(template.get("class").split("=")[1])
                if assessment in self.assessment_order:  # Reject invalid assessment classes (e.g. if someone has vandalised the template)
                    assessments.append(assessment)
            except ValueError:  # The WikiProject template may not have an assessment parameter
                continue  # Skip to the next one

        if len(assessments) == 0:
            if "WikiProject Disambiguation" in talk_page.text:
                return "dab", False, False
            else:
                return "unassessed", False, False
        elif len(assessments) > 1:
            assessments.sort(key=lambda x: self.assessment_order.index(x) if x in self.assessment_order else 255)
        return assessments[0], is_dga, is_ffa

    # The relevant article will be the first link in a line
    @staticmethod
    def get_article_link(line):
        for item in line:
            if "[[" in item and "<" not in item:
                bare_name = str(item).strip("[]'")
                if "|" in bare_name:
                    return bare_name.split("|")[0]
                else:
                    return bare_name
        return None

    def treat_page(self):
        # Grab the page text and parse it
        text = self.current_page.text
        wikicode = mwparserfromhell.parse(text, skip_style_tags=True)

        # Count the articles in each section and update the header accordingly
        for section in wikicode.get_sections(include_lead=False):
            article_count = section.count("# {{Icon")
            if article_count == 0:
                article_count = section.count("* {{Icon")
            old_header_match = re.match(r"(=+)\s*(.+?)\s*[\(:]\s*?([0-9,]+)\s*(?:articles?)?\s*(/\s*[0-9,]+)?\s*(?:articles?| quota)?\)?\s*=+", str(section))
            has_quota = "quota" in str(section)
            if old_header_match is None:
                continue
            old_header_groups = old_header_match.groups()
            new_header = "{0}{1} ({2}{4} article{3}{5}){0}".format(old_header_groups[0],
                                                                old_header_groups[1],
                                                                article_count,
                                                                "" if article_count == 1 or has_quota else "s",
                                                                old_header_groups[3] if len(old_header_groups) > 3 and old_header_groups[3] is not None else "",
                                                                " quota" if has_quota else "")

            new_header = new_header.replace("article quota", "quota")
            section.replace(old_header_match.group(0), new_header)

        # Add all the top-level headings together for the 'total articles' count
        total_count = 0
        for i in range(1,10):
            top_level_sections = wikicode.get_sections(levels=[i])
            if len(top_level_sections) > 0:
                for section in top_level_sections:
                    heading = str(section.filter_headings()[0])
                    heading_match = re.search(r"([0-9,]+)\s*(?:articles?)?\s*(/\s*[0-9,]+)?\s*(?:articles?| quota)?\)", heading)
                    if heading_match is None:
                        continue
                    total_count += int(heading_match.group(1))
                break

        # Update the 'total articles' count
        for template in wikicode.filter_templates():
            if template.name.matches("huge"):
                denominator = ""
                param = template.get("1")
                if "/" in param:
                    denominator = "/{}".format(param.split("/")[-1].strip("'"))
                template.add("1", "Total articles: {}{}".format(total_count, denominator))

        if not self.skip_assessment:
            # Split article into individual lines
            line_list = [list(group) for k, group in groupby(wikicode.filter(), lambda x: "\n" in x) if not k]

            # Process each line, looking for article links, then check their assessment
            for line in line_list:
                if line[0] == "#" or line[0] == "*":
                    article_title = self.get_article_link(line)
                    if article_title is None or "Wikipedia:" in article_title or "Category:" in article_title or "User:" in article_title or "Template:" in article_title or "Portal:" in article_title:
                        continue
                    article_assessment, is_dga, is_ffa = self.get_vital_article_quality(article_title)
                    print("Getting assessment for {}: {}, {}, {}".format(article_title, article_assessment, is_dga, is_ffa))
                    
                    count = 0
                    dga_found = False
                    ffa_found = False
                    first_templ = None
                    for item in line:
                        if "{{icon" in item.lower():
                            first_templ = item
                            try:
                                existing_assessment = item.get("1").lower()
                            except ValueError:  # Template may not have parameters
                                continue
                            if existing_assessment != article_assessment and existing_assessment not in self.no_replace_list and count < 1:  # Don't just change capitalisation, don't replace DGA or FFA
                                item.add("1", article_assessment)
                            dga_found |= (existing_assessment == "dga")
                            ffa_found |= (existing_assessment == "ffa")
                            
                            if (dga_found and article_assessment == "ga") or \
                                (ffa_found and article_assessment == "fa"):  # Remove DGA template if article is now a GA / FFA if FA
                                wikicode.remove(item)
                            count += 1
                    
                    if (is_dga and not dga_found):
                        wikicode.insert_after(first_templ, " {{icon|dga}}")
                    if (is_ffa and not ffa_found):
                        wikicode.insert_after(first_templ, " {{icon|ffa}}")

        if (self.check_task_switch_is_on()):
            # Save the updated text to the page
            self.put_current(str(wikicode),
                            summary="([[Wikipedia:Bots/Requests for approval/Bot0612 9|BOT in trial]]) Updating section counts{}".format(" and WikiProject assessments" if not self.skip_assessment else ""))
        else:
            print("Switch for task {} is off, terminating".format(self.task_number))
            exit(1)

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
