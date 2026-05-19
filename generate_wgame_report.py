#!/usr/bin/env python3
"""Generate Wgame weekly report with all data and comparisons"""

# KPIs
KPIs = {
    "overall_roi_7": 6.8,
    "overall_actual_roi": 4.1,
    "android_actual_roi": 5.4,
    "ios_actual_roi": 3.6,
    "google_actual_roi": 3.4,
    "facebook_actual_roi": 2.8,
    "tiktok_actual_roi": 4.0,
    "almedia_actual_roi": 8.0
}

def format_number(num, decimals=2):
    if num is None:
        return "-"
    return f"{num:.{decimals}f}"

def format_percent(num):
    if num is None:
        return "-"
    return f"{num:.2f}%"

def calc_change(current, previous):
    if previous is None or previous == 0:
        return None
    return ((current - previous) / previous) * 100

def format_change(current, previous, is_percent=False):
    change = calc_change(current, previous)
    if change is None:
        return "-"
    prefix = "+" if change >= 0 else ""
    if is_percent:
        return f"{prefix}{change:.2f}%"
    return f"{prefix}{change:.2f}%"

# Week before last (2026-05-04~2026-05-10) - store table
week_before_last_store = {
    "Android": {"cost": 98815.78, "installs": 83021, "cpi": 1.19, "roi_7d": 5.9, "retention_d2": 17.14},
    "iOS": {"cost": 168022.89, "installs": 73076, "cpi": 2.3, "roi_7d": 3.02, "retention_d2": 16.1},
    "PC": {"cost": 2936.82, "installs": 1839, "cpi": 1.6, "roi_7d": 19.63, "retention_d2": 23.0}
}

# Two weeks before (2026-04-27~2026-05-03) - store table
two_weeks_before_store = {
    "Android": {"cost": 88303.49, "installs": 73300, "cpi": 1.2, "roi_7d": 7.14, "retention_d2": 16.51},
    "iOS": {"cost": 172412.34, "installs": 78910, "cpi": 2.18, "roi_7d": 4.04, "retention_d2": 17.25},
    "PC": {"cost": 2979.17, "installs": 1892, "cpi": 1.57, "roi_7d": 12.51, "retention_d2": 25.69}
}

# Last week (2026-05-11~2026-05-17) - store table
last_week_store = {
    "Android": {"cost": 118664.92, "installs": 102548, "cpi": 1.16, "actual_roi": 5.12, "retention_d2": 17.03},
    "iOS": {"cost": 168134.21, "installs": 90159, "cpi": 1.86, "actual_roi": 4.1, "retention_d2": 16.94},
    "PC": {"cost": 3312.72, "installs": 1950, "cpi": 1.7, "actual_roi": 12.59, "retention_d2": 24.31}
}

# Android channels - Last week
android_channels = [
    {"channel": "Facebook", "cost": 24621.88, "installs": 66753, "cpi": 0.37, "actual_roi": 1.94, "roi_1d": 0.74, "retention_d2": 15.7},
    {"channel": "Google", "cost": 68387.95, "installs": 11818, "cpi": 5.79, "actual_roi": 3.83, "roi_1d": 0.87, "retention_d2": 20.09},
    {"channel": "Tiktok", "cost": 11089.69, "installs": 6080, "cpi": 1.82, "actual_roi": 4.17, "roi_1d": 3.38, "retention_d2": 18.75},
    {"channel": "Almedia", "cost": 12769.0, "installs": 1642, "cpi": 7.78, "actual_roi": 0.86, "roi_1d": 0.42, "retention_d2": 52.44},
    {"channel": "Applovin", "cost": 1278.88, "installs": 285, "cpi": 4.49, "actual_roi": 1.51, "roi_1d": 0.51, "retention_d2": 18.95},
    {"channel": "Fyber", "cost": 517.52, "installs": 41, "cpi": 12.62, "actual_roi": 3.41, "roi_1d": 0.54, "retention_d2": 39.02},
]

# iOS channels - Last week
ios_channels = [
    {"channel": "Facebook", "cost": 92730.55, "installs": 39082, "cpi": 2.37, "actual_roi": 1.2, "roi_1d": 0.6, "retention_d2": 18.38},
    {"channel": "Applovin", "cost": 23361.91, "installs": 7789, "cpi": 3.0, "actual_roi": 0.26, "roi_1d": 0.1, "retention_d2": 13.03},
    {"channel": "Tiktok", "cost": 19119.02, "installs": 4903, "cpi": 3.9, "actual_roi": 0.65, "roi_1d": 0.23, "retention_d2": 18.62},
    {"channel": "Google", "cost": 29161.03, "installs": 3357, "cpi": 8.69, "actual_roi": 0.35, "roi_1d": 0.17, "retention_d2": 15.46},
    {"channel": "Apple Ads", "cost": 3761.7, "installs": 1782, "cpi": 2.11, "actual_roi": 29.85, "roi_1d": 4.8, "retention_d2": 20.82},
]

# Android countries - Last week (2026-05-11~2026-05-17)
android_countries_last = [
    {"country": "us", "cost": 23005.12, "installs": 2349, "cpi": 9.79, "actual_roi": 6.0},
    {"country": "de", "cost": 14867.46, "installs": 1725, "cpi": 8.62, "actual_roi": 3.52},
    {"country": "gb", "cost": 6861.14, "installs": 1336, "cpi": 5.14, "actual_roi": 1.16},
    {"country": "fr", "cost": 6619.1, "installs": 2175, "cpi": 3.04, "actual_roi": 3.58},
    {"country": "pl", "cost": 6618.34, "installs": 1898, "cpi": 3.49, "actual_roi": 9.2},
    {"country": "it", "cost": 6404.3, "installs": 1782, "cpi": 3.59, "actual_roi": 8.77},
    {"country": "jp", "cost": 7601.28, "installs": 537, "cpi": 14.16, "actual_roi": 1.47},
    {"country": "au", "cost": 2433.86, "installs": 356, "cpi": 6.84, "actual_roi": 3.87},
    {"country": "ca", "cost": 1671.76, "installs": 356, "cpi": 4.7, "actual_roi": 2.45},
    {"country": "nl", "cost": 1675.64, "installs": 485, "cpi": 3.45, "actual_roi": 9.15},
    {"country": "th", "cost": 601.81, "installs": 1383, "cpi": 0.44, "actual_roi": 5.51},
    {"country": "tr", "cost": 2787.5, "installs": 3551, "cpi": 0.78, "actual_roi": 2.47},
    {"country": "vn", "cost": 2161.32, "installs": 2069, "cpi": 1.04, "actual_roi": 16.71},
    {"country": "id", "cost": 2590.92, "installs": 9022, "cpi": 0.29, "actual_roi": 2.37},
    {"country": "br", "cost": 1492.48, "installs": 7626, "cpi": 0.2, "actual_roi": 1.49},
    {"country": "my", "cost": 1675.95, "installs": 1458, "cpi": 1.15, "actual_roi": 8.65},
    {"country": "es", "cost": 2127.48, "installs": 1403, "cpi": 1.52, "actual_roi": 0.91},
    {"country": "ru", "cost": 1278.88, "installs": 3073, "cpi": 0.42, "actual_roi": 29.24},
    {"country": "sa", "cost": 272.65, "installs": 396, "cpi": 0.69, "actual_roi": 0.24},
    {"country": "in", "cost": 116.25, "installs": 9920, "cpi": 0.01, "actual_roi": 4.73},
]

# Android countries - Week before (2026-05-04~2026-05-10)
android_countries_before = {
    "us": {"cost": 22278.25, "installs": 1949, "cpi": 11.43, "actual_roi": 9.09},
    "de": {"cost": 11180.15, "installs": 1427, "cpi": 7.83, "actual_roi": 3.15},
    "gb": {"cost": 5293.09, "installs": 1158, "cpi": 4.57, "actual_roi": 9.99},
    "fr": {"cost": 5845.52, "installs": 2198, "cpi": 2.66, "actual_roi": 6.26},
    "pl": {"cost": 2177.39, "installs": 1506, "cpi": 1.45, "actual_roi": 3.97},
    "it": {"cost": 2664.76, "installs": 1791, "cpi": 1.49, "actual_roi": 2.35},
    "jp": {"cost": 5058.28, "installs": 656, "cpi": 7.71, "actual_roi": 9.8},
    "au": {"cost": 1964.53, "installs": 298, "cpi": 6.59, "actual_roi": 28.34},
    "ca": {"cost": 1860.53, "installs": 236, "cpi": 7.88, "actual_roi": 1.8},
    "nl": {"cost": 1591.16, "installs": 430, "cpi": 3.7, "actual_roi": 0.8},
    "th": {"cost": 450.51, "installs": 446, "cpi": 1.01, "actual_roi": 2.19},
    "tr": {"cost": 3771.29, "installs": 4083, "cpi": 0.92, "actual_roi": 16.56},
    "vn": {"cost": 1561.92, "installs": 1901, "cpi": 0.82, "actual_roi": 6.89},
    "id": {"cost": 2371.27, "installs": 8437, "cpi": 0.28, "actual_roi": 3.44},
    "br": {"cost": 1493.37, "installs": 8154, "cpi": 0.18, "actual_roi": 3.58},
    "my": {"cost": 1660.47, "installs": 1490, "cpi": 1.11, "actual_roi": 2.99},
    "es": {"cost": 2220.93, "installs": 1555, "cpi": 1.43, "actual_roi": 1.13},
    "ru": {"cost": 0, "installs": 2670, "cpi": 0, "actual_roi": 0},
    "sa": {"cost": 192.4, "