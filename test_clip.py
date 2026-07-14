from PIL import ImageGrab
img = ImageGrab.grabclipboard()
if img:
    print(img.size, img.mode)
else:
    print('No image')
