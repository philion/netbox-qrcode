
import math
import os

from PIL import Image, ImageFont, ImageDraw
import dotenv
import qrcode
import requests
import pynetbox


from utilities import get_qr_text, get_qr, get_concat


# all numbers translate to pixels? inch? they need to be float, then
class SheetTemplate():
    rows: int  # number of labels down a page
    cols: int  # number of labels across a page
    height: float # inches
    width: float
    margin_top: float     = 0.0  # page margins
    margin_bottom: float  = 0.0
    margin_left: float    = 0.0
    margin_right: float   = 0.0
    padding_bottom: float = 0.0
    padding_right: float  = 0.0
    scale: int = 300 # dpi

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    @property
    def page_width(self):
        width = self.margin_left + (self.cols * self.width) + ((self.cols-1) * self.padding_right)
        return int(self.scale * width)

    @property
    def page_height(self):
        height = self.margin_top + (self.rows * self.height) + ((self.rows-1) * self.padding_bottom)
        return int(self.scale * height)

    @property
    def page_size(self):
        return (self.page_width, self.page_height)

    @property
    def label_width(self):
        return int(self.scale * self.width)

    @property
    def label_height(self):
        return int(self.scale * self.height)

    @property
    def label_size(self):
        return (self.label_width, self.label_height)

    def label_box(self, col: int, row: int):
        x = int(self.scale * (self.margin_left + col * (self.width + self.padding_right)))
        y = int(self.scale * (self.margin_top + row * (self.height + self.padding_bottom)))
        box = (x, y) #, x + self.label_width, y + self.label_height)
        return box

    def render_text(self, max_size, text:list[str], font='TahomaBold'):
        font_size = 56
        text_str = '\n'.join(text)
        tmpimg = Image.new('L', max_size, 'white')
        text_too_large = True
        while text_too_large:
            file_path = f"fonts/{font}.ttf"
            try:
                fnt = ImageFont.truetype(file_path, font_size)
            except Exception:
                fnt = ImageFont.load_default()

            draw = ImageDraw.Draw(tmpimg)
            _, _, w, h = draw.textbbox((0, 0), text=text_str, font=fnt)
            if w < max_size[0] - 4 and h < max_size[1] - 4:
                text_too_large = False
            font_size -= 1

        img = Image.new('L', (w, h), 'white')
        draw = ImageDraw.Draw(img)
        draw.text((0, 0), text_str, font=fnt, fill='black')
        return img


    def render_label(self, url, text:list[str]):
        # given the label_height, render a QR code.
        qr = qrcode.QRCode() # NEEDED? **kwargs)
        qr.add_data(url)
        qr.make(fit=True)
        qr_img = qr.make_image()
        qr_img = qr_img.get_image()

        # resize the QR to label size
        qr_img.thumbnail(self.label_size, Image.Resampling.LANCZOS)

        text_width = self.label_width - qr_img.size[0]
        dsi = self.render_text((text_width, self.label_height), text)

        label = get_concat(qr_img, dsi)

        return label


    def render_pages(self, qr_imgs):
        """ Given an array of image, tile those images according to the
        layout provided in the sheet template.
        """
        num_pages = math.ceil(len(qr_imgs) / (self.rows * self.cols))

        # create list of page images
        mode = qr_imgs[0].mode
        page_size = (self.page_width, self.page_height)
        pages = [Image.new(mode, page_size, 'white') for _ in range(num_pages)]

        for idx, img in enumerate(qr_imgs):
            page = math.floor(idx / (self.rows * self.cols))
            row = int(idx / self.cols) - page * self.rows
            col = idx % self.cols

            #box = self.label_box(col, row)
            x = int(self.scale * (self.margin_left + col * (self.width + self.padding_right)))
            y = int(self.scale * (self.margin_top + row * (self.height + self.padding_bottom)))
            print(f"{idx} - {img.size} -  page:{page} row:{row} col:{col} box:{(x, y)}")

            pages[page].paste(img, (x, y))

        return pages


    def render_document(self, qr_imgs, filename):
        # render the QR images onto a template
        pages = self.render_pages(qr_imgs)

        # print the pdf
        dpi = (self.scale, self.scale)
        pages[0].save(filename, save_all=True, append_images=pages[1:], dpi=dpi)


class QRInventory():
    def __init__(self, url: str, token: str):
        self.url = url
        self.client = pynetbox.api(url, token)

        # create a custom session to disable SSL validation, as per
        # https://pynetbox.readthedocs.io/en/latest/advanced.html#ssl-verification
        # FIXME This should be removed as soon as real certs are in place.
        session = requests.Session()
        session.verify = False
        self.client.http_session = session


    @classmethod
    def fromenv(cls):
        url = os.getenv('NETBOX_URL')
        token = os.getenv('NETBOX_TOKEN')
        return cls(url, token)


    @classmethod
    def fromenvfile(cls):
        dotenv.load_dotenv()
        return cls.fromenv()


    def render_qr(self, url, text):
        qr_img = get_qr(url)
        dsi = get_qr_text(qr_img.size, text)
        resimg = get_concat(qr_img, dsi)
        return resimg


    def print_inventory(self, template:SheetTemplate, filename:str):
        qr_imgs = []

        # generate a QR code for each item in the inventory
        for device in self.client.dcim.devices.all():
            fields = [
                device.name,
                f"{device.device_role} {device.device_type}",
                str(device.site),
                device.serial,
            ]
            qr_imgs.append(template.render_label(device.url, fields))

        # render the document from the images
        template.render_document(qr_imgs, filename)


def main():
    template = SheetTemplate(
        rows = 10,
        cols = 3,
        height = 1,     # inches
        width = 2.625,  # inches
        margin_top = 0.0,
        margin_bottom = 0.25,
        margin_left = 0.0,
        margin_right = 0.25,
        padding_bottom = 0.0,
        padding_right = 0.13
    )

    inventory = QRInventory.fromenvfile()
    inventory.print_inventory(template, "inventory.pdf")


if __name__ == '__main__':
    main()
