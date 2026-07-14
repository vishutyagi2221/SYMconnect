from PIL import Image
img = Image.open('D:/ControlViewer/symconnect/static/logo.png').convert('RGBA')
data = img.getdata()
new_data = []
for item in data:
    if item[0] > 240 and item[1] > 240 and item[2] > 240:
        new_data.append((255, 255, 255, 0))
    else:
        new_data.append(item)
img.putdata(new_data)
img.save('D:/ControlViewer/symconnect/static/logo.png', 'PNG')
img.save('D:/ControlViewer/symconnect/static/icon.ico', format='ICO', sizes=[(256, 256)])
