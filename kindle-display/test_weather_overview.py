import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.weather_overview import normalize_weather, hour_slots, future_days, weather_summary, icon_name


class WeatherOverviewTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026,9,4,23,15,tzinfo=ZoneInfo('Asia/Shanghai'))

    def test_nullable_api_fields_stay_unavailable(self):
        weather = normalize_weather({'current': {'temperature_2m': None}, 'daily': {
            'time': ['2026-09-04'], 'temperature_2m_max': [None]}, 'hourly': {
            'time': ['2026-09-05T00:00'], 'precipitation_probability': [None]}}, {})
        self.assertEqual(weather['temperature'], '--')
        self.assertEqual(weather['high'], '--')
        self.assertEqual(weather['hourly'][0]['rain'], '--')
        self.assertEqual(weather['hourly'][0]['wind'], '--')
        self.assertEqual(weather['rain_now'], '--')
        self.assertEqual(weather_summary(weather,self.now)[0], '逐时预报暂不可用')

    def test_hourly_and_current_wind_fields_are_normalized(self):
        weather = normalize_weather({'current': {
            'time': '2026-09-04T23:15', 'temperature_2m': 28.4, 'apparent_temperature': 31.1,
            'weather_code': 95, 'is_day': 0, 'wind_speed_10m': 11.2,
            'wind_direction_10m': 225, 'wind_gusts_10m': 18.8,
        }, 'hourly': {
            'time': ['2026-09-04T23:00'], 'temperature_2m': [28.1],
            'apparent_temperature': [33.6], 'weather_code': [95],
            'precipitation_probability': [68], 'wind_speed_10m': [10.4],
            'wind_direction_10m': [224], 'wind_gusts_10m': [17.8], 'is_day': [0],
        }}, {95: '雷暴'})
        self.assertEqual((weather['wind'], weather['wind_direction'], weather['gust']), (11, 225, 19))
        self.assertEqual(weather['rain_now'], 68)
        self.assertEqual(weather['hourly'][0]['apparent'], 34)
        self.assertEqual(weather['hourly'][0]['wind'], 10)

    def test_midnight_slots_skip_past_keep_missing_and_timezone(self):
        weather = {'hourly': [
            {'time':'2026-09-04T23:00','temperature':25},
            {'time':'2026-09-05T00:00','temperature':24},
            {'time':'2026-09-04T18:00:00+00:00','temperature':23},
            {'time':'2026-09-05T06:00','temperature':22},
        ]}
        slots = hour_slots(weather,self.now)
        self.assertEqual([item['stamp'].hour for item in slots],[0,2,4,6,8,10])
        self.assertEqual(slots[0]['temperature'],24)
        self.assertEqual(slots[1]['temperature'],23)
        self.assertNotIn('temperature',slots[2])
        self.assertEqual(slots[3]['temperature'],22)

    def test_forecast_uses_dates_and_excludes_today(self):
        weather = {'forecast': [{'date':'2026-09-04','high':40}, {'date':'2026-09-06','high':30}]}
        days = future_days(weather,self.now)
        self.assertEqual([day.isoformat() for day,_ in days],['2026-09-05','2026-09-06','2026-09-07'])
        self.assertEqual(days[0][1],{})
        self.assertEqual(days[1][1]['high'],30)

    def test_summary_not_inferred_from_daily_rain(self):
        self.assertEqual(weather_summary({'rain':100},self.now)[0],'逐时预报暂不可用')
        rainy = {'hourly':[{'time':'2026-09-05T03:00','code':61,'rain':70}]}
        self.assertEqual(weather_summary(rainy,self.now)[0],'明晨可能有雨')
        rainy['hourly'][0]['code']=95
        self.assertIn('雷雨',weather_summary(rainy,self.now)[0])

    def test_day_night_and_unknown_icons(self):
        self.assertEqual(icon_name(0,False),'night-clear')
        self.assertEqual(icon_name(2,False),'night-alt-cloudy')
        self.assertEqual(icon_name(0,True),'day-sunny')
        self.assertEqual(icon_name(None),'na')


if __name__=='__main__': unittest.main()
