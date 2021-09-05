# Standard Python libraries.
import logging
import os
import random
import sys
import time
import urllib

# Third party Python libraries.
from bs4 import BeautifulSoup
import requests

# Custom Python libraries.

__version__ = "1.2.0"

# Logging
ROOT_LOGGER = logging.getLogger("yagooglesearch")
# ISO 8601 datetime format by default.
LOG_FORMATTER = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)s] %(message)s")

# Setup file logging.
log_file_handler = logging.FileHandler("yagooglesearch.py.log")
log_file_handler.setFormatter(LOG_FORMATTER)
ROOT_LOGGER.addHandler(log_file_handler)

# Setup console logging.
console_handler = logging.StreamHandler()
console_handler.setFormatter(LOG_FORMATTER)
ROOT_LOGGER.addHandler(console_handler)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.131 Safari/537.36"

# Load the list of valid user agents from the install folder.  The search order is:
#   1) user_agents.txt
#   2) default USER_AGENT
install_folder = os.path.abspath(os.path.split(__file__)[0])

try:
    user_agents_file = os.path.join(install_folder, "user_agents.txt")
    with open(user_agents_file) as fh:
        user_agents_list = [_.strip() for _ in fh.readlines()]

except Exception:
    user_agents_list = [USER_AGENT]


def get_tbs(from_date, to_date):
    """Helper function to format the tbs parameter dates.  Note that verbatim mode also uses the &tbs= parameter, but
    this function is just for customized search periods.

    :param datetime.date from_date: Python date object, e.g. datetime.date(2021, 1, 1)
    :param datetime.date to_date: Python date object, e.g. datetime.date(2021, 6, 1)

    :rtype: str
    :return: Dates encoded in tbs format.
    """

    from_date = from_date.strftime("%m/%d/%Y")
    to_date = to_date.strftime("%m/%d/%Y")

    formatted_tbs = f"cdr:1,cd_min:{from_date},cd_max:{to_date}"

    return formatted_tbs


class SearchClient:
    def __init__(
        self,
        query,
        tld="com",
        lang="en",
        tbs="0",
        safe="off",
        start=0,
        num=100,
        country="",
        extra_params=None,
        max_search_result_urls_to_return=100,
        delay_between_paged_results_in_seconds=list(range(7, 18)),
        user_agent=None,
        http_429_cool_off_time_in_minutes=60,
        http_429_cool_off_factor=1.1,
        proxy="",
        verify_ssl=True,
        verbosity=5,
    ):

        """
        SearchClient
        :param str query: Query string. Must NOT be url-encoded.
        :param str tld: Top level domain.
        :param str lang: Language.
        :param str tbs: Verbatim search or time limits (e.g., "qdr:h" => last hour, "qdr:d" => last 24 hours, "qdr:m"
            => last month).
        :param str safe: Safe search.
        :param int start: First page of results to retrieve.
        :param int num: Max number of results to pull back per page.  Capped at 100 by Google.
        :param str country: Country or region to focus the search on. Similar to changing the TLD, but does not yield
            exactly the same results.  Only Google knows why...
        :param dict extra_params: A dictionary of extra HTTP GET parameters, which must be URL encoded. For example if
            you don't want Google to filter similar results you can set the extra_params to {'filter': '0'} which will
            append '&filter=0' to every query.
        :param int max_search_result_urls_to_return: Max URLs to return for the entire Google search.
        :param int delay_between_paged_results_in_seconds: Time to wait between HTTP requests for consecutive pages for
            the same search query.
        :param str user_agent: Hard-coded user agent for the HTTP requests.
        :param int http_429_cool_off_time_in_minutes: Minutes to sleep if an HTTP 429 is detected.
        :param float http_429_cool_off_factor: Factor to multiply by http_429_cool_off_time_in_minutes for each HTTP 429
            detected.
        :param str proxy: HTTP(S) or SOCKS5 proxy to use.
        :param bool verify_ssl: Verify the SSL certificate to prevent traffic interception attacks. Defaults to True.
            This may need to be disabled in some HTTPS proxy instances.
        :param int verbosity: Logging and console output verbosity.

        :rtype: List of str
        :return: List of found URLs.
        """

        self.query = urllib.parse.quote_plus(query)
        self.tld = tld
        self.lang = lang
        self.tbs = tbs
        self.safe = safe
        self.start = start
        self.num = num
        self.country = country
        self.extra_params = extra_params
        self.max_search_result_urls_to_return = max_search_result_urls_to_return
        self.delay_between_paged_results_in_seconds = delay_between_paged_results_in_seconds
        self.user_agent = user_agent
        self.http_429_cool_off_time_in_minutes = http_429_cool_off_time_in_minutes
        self.http_429_cool_off_factor = http_429_cool_off_factor
        self.proxy = proxy
        self.verify_ssl = verify_ssl
        self.verbosity = verbosity

        # Assign log level.
        ROOT_LOGGER.setLevel((6 - self.verbosity) * 10)

        # Argument checks.
        if self.num > 100:
            ROOT_LOGGER.warning("The largest value allowed by Google for num is 100.  Setting num to 100.")
            self.num = 100

        # Initialize cookies to None, will be updated with each request in get_page().
        self.cookies = None

        # Used later to ensure there are not any URL parameter collisions.
        self.url_parameters = ("btnG", "cr", "hl", "num", "q", "safe", "start", "tbs")

        # Default user agent, unless instructed by the user to change it.
        if not user_agent:
            self.user_agent = self.assign_random_user_agent()

        # Update the URLs with the initial SearchClient attributes.
        self.update_urls()

        # Initialize proxy_dict.
        self.proxy_dict = {}

        # Update proxy_dict if a proxy is provided.
        if proxy:

            # Standardize case since the scheme will be checked against a hard-coded list.
            self.proxy = proxy.lower()

            urllib_object = urllib.parse.urlparse(self.proxy)
            scheme = urllib_object.scheme

            if scheme not in ["http", "https", "socks5", "socks5h"]:
                ROOT_LOGGER.error(
                    f'The provided proxy scheme ("{scheme}") is not valid and must be either "http", "https", "socks5"'
                    ', or "socks5h"'
                )
                sys.exit(1)

            self.proxy_dict = {
                "http": self.proxy,
                "https": self.proxy,
            }

        # Suppress warning messages if verify_ssl is disabled.
        if not self.verify_ssl:
            requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

    def update_urls(self):
        """Update search URLs being used."""

        # URL templates to make Google searches.
        self.url_home = f"https://www.google.{self.tld}/"

        # First search requesting the default 10 search results.
        self.url_search = (
            f"https://www.google.{self.tld}/search?hl={self.lang}&"
            f"q={self.query}&btnG=Google+Search&tbs={self.tbs}&safe={self.safe}&"
            f"cr={self.country}&filter=0"
        )

        # Subsequent searches starting at &start= and retrieving 10 search results at a time.
        self.url_next_page = (
            f"https://www.google.{self.tld}/search?hl={self.lang}&"
            f"q={self.query}&start={self.start}&tbs={self.tbs}&safe={self.safe}&"
            f"cr={self.country}&filter=0"
        )

        # First search requesting more than the default 10 search results.
        self.url_search_num = (
            f"https://www.google.{self.tld}/search?hl={self.lang}&"
            f"q={self.query}&num={self.num}&btnG=Google+Search&tbs={self.tbs}&"
            f"safe={self.safe}&cr={self.country}&filter=0"
        )

        # Subsequent searches starting at &start= and retrieving &num= search results at a time.
        self.url_next_page_num = (
            f"https://www.google.{self.tld}/search?hl={self.lang}&"
            f"q={self.query}&start={self.start}&num={self.num}&tbs={self.tbs}&"
            f"safe={self.safe}&cr={self.country}&filter=0"
        )

    def assign_random_user_agent(self):
        """Assign a random user agent string.

        :rtype: str
        :return: Random user agent string.
        """

        random_user_agent = random.choice(user_agents_list)
        self.user_agent = random_user_agent

        return random_user_agent

    def filter_search_result_urls(self, link):
        """Filter links found in the Google result pages HTML code.  Valid results are absolute URLs not pointing to a
        Google domain, like images.google.com or googleusercontent.com.  Returns None if the link doesn't yield a valid
        result.

        :rtype: str
        :return: URL string
        """

        ROOT_LOGGER.debug(f"pre filter_search_result_urls() link: {link}")

        try:
            # Extract URL from parameter.  Once in a while the full "http://www.google.com/url?" exists instead of just
            # "/url?".  After a re-run, it disappears and "/url?" is present...might be a caching thing?
            if link.startswith("/url?") or link.startswith("http://www.google.com/url?"):
                urlparse_object = urllib.parse.urlparse(link, scheme="http")

                # The "q" key exists most of the time.
                try:
                    link = urllib.parse.parse_qs(urlparse_object.query)["q"][0]
                # Sometimes, only the "url" key does though.
                except KeyError:
                    link = urllib.parse.parse_qs(urlparse_object.query)["url"][0]

            # Create a urlparse object.
            urlparse_object = urllib.parse.urlparse(link, scheme="http")

            # Exclude urlparse objects without a netloc value.
            if not urlparse_object.netloc:
                ROOT_LOGGER.debug(
                    f"Excluding URL because it does not contain a urllib.parse.urlparse netloc value: {link}"
                )
                link = None

            # TODO: Generates false positives if specifing an actual Google site, e.g. "site:google.com fiber".
            if urlparse_object.netloc and ("google" in urlparse_object.netloc.lower()):
                ROOT_LOGGER.debug(f'Excluding URL because it contains "google": {link}')
                link = None

        except Exception:
            link = None

        ROOT_LOGGER.debug(f"post filter_search_result_urls() link: {link}")

        return link

    def http_429_detected(self):
        """Increase the HTTP 429 cool off period."""

        new_http_429_cool_off_time_in_minutes = round(
            self.http_429_cool_off_time_in_minutes * self.http_429_cool_off_factor, 2
        )
        ROOT_LOGGER.info(
            f"Increasing HTTP 429 cool off time by a factor of {self.http_429_cool_off_factor}, "
            f"from {self.http_429_cool_off_time_in_minutes} minutes to {new_http_429_cool_off_time_in_minutes} minutes"
        )
        self.http_429_cool_off_time_in_minutes = new_http_429_cool_off_time_in_minutes

    def get_page(self, url):
        """
        Request the given URL and return the response page.

        :param str url: URL to retrieve.

        :rtype: str
        :return: Web page HTML retrieved for the given URL
        """

        headers = {
            "User-Agent": self.user_agent,
        }

        ROOT_LOGGER.info(f"Requesting URL: {url}")
        response = requests.get(
            url, proxies=self.proxy_dict, headers=headers, cookies=self.cookies, timeout=15, verify=self.verify_ssl
        )

        # Update the cookies.
        self.cookies = response.cookies

        # Extract the HTTP response code.
        http_response_code = response.status_code

        # debug_requests_response(response)
        ROOT_LOGGER.debug(f"    status_code: {http_response_code}")
        ROOT_LOGGER.debug(f"    headers: {headers}")
        ROOT_LOGGER.debug(f"    cookies: {self.cookies}")
        ROOT_LOGGER.debug(f"    proxy: {self.proxy}")
        ROOT_LOGGER.debug(f"    verify_ssl: {self.verify_ssl}")

        html = ""

        if http_response_code == 200:
            html = response.text
        elif http_response_code == 429:
            ROOT_LOGGER.warning("Google is blocking your IP for making too many requests in a specific time period.")
            ROOT_LOGGER.info(f"Sleeping for {self.http_429_cool_off_time_in_minutes} minutes...")
            time.sleep(self.http_429_cool_off_time_in_minutes * 60)
            self.http_429_detected()

            # Try making the request again.
            html = self.get_page(url)
        else:
            ROOT_LOGGER.warning(f"HTML response code: {http_response_code}")

        return html

    def search(self):
        """Start the Google search.

        :rtype: List of str
        :return: List of URLs found
        """

        # Set of URLs for the results found.
        unique_urls_set = set()

        # Count the number of valid, non-duplicate links found.
        total_valid_links_found = 0

        # If no extra_params is given, create an empty dictionary. We should avoid using an empty dictionary as a
        # default value in a function parameter in Python.
        if not self.extra_params:
            self.extra_params = {}

        # Check extra_params for overlapping parameters.
        for builtin_param in self.url_parameters:
            if builtin_param in self.extra_params.keys():
                raise ValueError(f'GET parameter "{builtin_param}" is overlapping with the built-in GET parameter')

        # Simulates browsing to the google.com home page and retrieving the initial cookie.
        html = self.get_page(self.url_home)

        # Loop until we reach the maximum result results found or there are no more search results found to reach
        # max_search_result_urls_to_return.
        while total_valid_links_found <= self.max_search_result_urls_to_return:

            ROOT_LOGGER.info(
                f"Stats: start={self.start}, num={self.num}, total_valid_links_found={total_valid_links_found} / "
                f"max_search_result_urls_to_return={self.max_search_result_urls_to_return}"
            )

            # Prepare the URL for the search request.
            if self.start:
                if self.num == 10:
                    url = self.url_next_page
                else:
                    url = self.url_next_page_num
            else:
                if self.num == 10:
                    url = self.url_search
                else:
                    url = self.url_search_num

            # Append extra GET parameters to the URL.  This is done on every iteration because we're rebuilding the
            # entire URL at the end of this loop.
            for key, value in self.extra_params.items():
                key = urllib.parse.quote_plus(key)
                value = urllib.parse.quote_plus(value)
                url += f"&{key}={value}"

            # Request Google search results.
            html = self.get_page(url)

            # Create the BeautifulSoup object.
            soup = BeautifulSoup(html, "html.parser")

            # Find all HTML <a> elements.
            try:
                anchors = soup.find(id="search").find_all("a")
            # Sometimes (depending on the User-Agent) there is no id "search" in html response.
            except AttributeError:
                # Remove links from the top bar.
                gbar = soup.find(id="gbar")
                if gbar:
                    gbar.clear()
                anchors = soup.find_all("a")

            # Used to determine if another page of search results needs to be requested.  If 100 search results are
            # requested per page, but the current page of results is less than that, no need to search the next page for
            # results because there won't be any.  Prevents fruitless queries and costing a pointless search request.
            valid_links_found_in_this_search = 0

            # Process every anchored URL.
            for a in anchors:

                # Get the URL from the anchor tag.
                try:
                    link = a["href"]
                except KeyError:
                    ROOT_LOGGER.warning(f"No href for link: {link}")
                    continue

                # Filter invalid links and links pointing to Google itself.
                link = self.filter_search_result_urls(link)
                if not link:
                    continue

                # Check if URL has already been found.
                if link not in unique_urls_set:

                    # Increase the counters.
                    valid_links_found_in_this_search += 1
                    total_valid_links_found += 1

                    ROOT_LOGGER.info(f"Found unique URL #{total_valid_links_found}: {link}")
                    unique_urls_set.add(link)

                # If we reached the limit of requested URLS, return with the results.
                if self.max_search_result_urls_to_return <= len(unique_urls_set):
                    # Convert to a list.
                    self.unique_urls_list = list(unique_urls_set)
                    return self.unique_urls_list

            # See comment for the "valid_links_found_in_this_search" variable.  This is because determining if a "Next"
            # URL page of results is not straightforward.  For example, this can happen if
            # max_search_result_urls_to_return=100, but there are only 93 total possible results.
            if valid_links_found_in_this_search != self.num:
                ROOT_LOGGER.info(
                    f"The number of valid search results ({valid_links_found_in_this_search}) was not the requested "
                    f"max results to pull back at once num=({self.num}) for this page.  That implies there won't be "
                    "any search results on the next page either.  Moving on..."
                )
                # Convert to a list.
                self.unique_urls_list = list(unique_urls_set)
                return self.unique_urls_list

            # Bump the starting page URL parameter for the next request.
            self.start += self.num

            # Refresh the URLs.
            self.update_urls()

            # If self.num == 10, this is the default search criteria.
            if self.num == 10:
                url = self.url_next_page
            # User has specified search criteria requesting more than 10 results at a time.
            else:
                url = self.url_next_page_num

            # Randomize sleep time between paged requests to make it look more human.
            random_sleep_time = random.choice(self.delay_between_paged_results_in_seconds)
            ROOT_LOGGER.info(f"Sleeping {random_sleep_time} seconds until retrieving the next page of results...")
            time.sleep(random_sleep_time)
