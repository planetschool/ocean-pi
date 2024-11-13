import board
import csv
import time
import gpiod

digital_converter = 0x48
i2c = board.I2C()
chip = gpiod.Chip('gpiochip4')

PORT_FLOW = 17
STAR_FLOW = 27

'''
GPIO.setmode(GPIO.BOARD)
water_flow_sensor_portside = GPIO.setup(PORT_FLOW, GPIO.IN)
button_line_port = chip.get_line(PORT_FLOW)
button_line_star = chip.get_line(STAR_FLOW)
button_line.request(consumer="Button", type=gpiod.LINE_REQ_DIR_IN)
'''

#water_flow_sensor_starbird = 

ADC_On = True

if ADC_On:
	import adafruit_ads1x15.ads1115 as ADS
	from adafruit_ads1x15.analog_in import AnalogIn
	ads = ADS.ADS1115(i2c)
	salinity_sensor = AnalogIn(ads, ADS.P1)
	temperature_sensor = AnalogIn(ads, ADS.P2)
	pH_sensor = AnalogIn(ads, ADS.P3)
	turbidity_sensor = AnalogIn(ads, ADS.P0)

LCD_On = True                                                                                                       
if LCD_On:
	import I2C_LCD_driver
	
	mylcd = I2C_LCD_driver.lcd()
	mylcd.lcd_display_string("The LCDjawn works", 1, 0)
	
while True:
	
	data = [
		time.localtime().tm_mon, 
		time.localtime().tm_mday, 
		time.localtime().tm_year, 
		time.localtime().tm_hour, 
		time.localtime().tm_min, 
		time.localtime().tm_sec
		]
	
	if ADC_On:
		
		salinity_value = salinity_sensor.value
		data.append(salinity_value)
		
		temperature_value = temperature_sensor.value
		float(temperature_value)
		temperature_value = temperature_value/1000
		temperature_value = (temperature_value * 9/5) + 32
		data.append(temperature_value)
		
		pH_value = pH_sensor.value
		data.append(pH_value)
		
		turbidity_value = turbidity_sensor.value
		data.append(turbidity_value)
			
		mylcd.lcd_display_string(f"Salinity: {salinity_value}       "  , 1, 0)
		time.sleep(3)
		
		mylcd.lcd_display_string(f"Temp: {temperature_value}      ", 1, 0)
		time.sleep(3)
		
		mylcd.lcd_display_string(f"pH: {pH_value}           ", 1, 0)
		time.sleep(3)
		
		mylcd.lcd_display_string(f"Turbidity: {turbidity_value}     ", 1, 0)
		time.sleep(3)
		
