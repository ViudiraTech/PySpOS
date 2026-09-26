'''
 *
 *      util.py
 *      Path and filename helpers for apps and spf apps.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import re


# Return the path of an app
def get_app_path(app_name: str) -> str:
    # apps/ under the current working directory
    return os.path.join(os.getcwd(), "apps", app_name)

# Return the path of an spf app
def get_spf_path(app_name: str) -> str:
    # spfapps/ under the current working directory
    return os.path.join(os.getcwd(), "spfapps", app_name)

# Report whether a filename is safe to use
def is_safe_filename(filename: str) -> bool:
    # A backslash is a path separator on Windows and a traversal spelling on every
    # platform, so '..\..\etc' has to be refused the same way '../' is; testing only
    # for '../' let it through and the write landed outside the directory.
    if "\\" in filename:
        return False
    return not (re.search(r'\.\./', filename) or os.path.isabs(filename))

