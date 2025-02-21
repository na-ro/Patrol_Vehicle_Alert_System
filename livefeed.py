from ultralytics import YOLO
import cv2
from sort.sort import *
from util import get_car, read_license_plate, write_csv_wimage, paddle_read_license_plate, write_csv, image_to_base64
from paddleocr import PaddleOCR, draw_ocr
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont
import numpy as np


def preprocess_image(image):
    # read image from specified path
    #image = cv2.imread(image) # Nat - commented this out since I'm not passing a file
    # upscale the image by 4x with the LANCZOS4 interpolation technique (makes edges sharper and upscales the most)
    resized_image = cv2.resize(image, None, fx=4, fy=4, interpolation=cv2.INTER_LANCZOS4)

    # apply gaussian blur to sharpen image as much as possible
    # filter kernel size specified at 7x7
    blurred = cv2.GaussianBlur(resized_image, (7,7), 0)

    # denoise the image
    # parameters: h=9 - noise removal strength of 9, templateWindowSize=10 - size of window to compare neighboring pixels,
    # searchWindowSize=21 - size of window to search for similar patches and average them
    denoised = cv2.fastNlMeansDenoisingColored(blurred, None, h=9, templateWindowSize=10, searchWindowSize=21)

    # apply CLAHE contrast increase
    # convert to LAB space (3 channels: Luminance, A = Green-Red, B = Blue-Yellow)
    lab = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    # actually create the CLAHE contrast filter to apply to the image
    # clipLimit=7 specifies the contrast enhancement, with higher values being stronger
    # tileGridSize=(25, 25) splits the image into the specified grid size to apply the enhancement
    clahe = cv2.createCLAHE(clipLimit=7, tileGridSize=(25, 25))
    
    # apply the contrast enhancement only in the Luminance channel
    l = clahe.apply(l)

    # merge the channels back together and convert back into BGR space for PaddleOCR
    lab = cv2.merge((l, a, b))
    contrast_enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    # convert the image to grayscale for easier processing/OCR
    gray = cv2.cvtColor(contrast_enhanced, cv2.COLOR_BGR2GRAY)

    # otsu thresholding
    # thresh=0 is automatically calculated
    # maxval=255 specifies the max intensity value for pixels going through the threshold. in this case, 255 is white
    # if a pixel ends up with a value greater than the calculated thresh, that pixel is then set to black, being set to white if otherwise.
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

    # invert the thresholded image to turn all white text into black
    # PaddleOCR seems to perform better with BOW instead of WOB in most cases
    inverted_thresh = cv2.bitwise_not(thresh)

    #cv2.imshow('img', inverted_thresh)
    #cv2.waitKey(0)

    # convert grayscale/thresh image back to 3 channels, as PaddleOCR requires 3
    return cv2.cvtColor(inverted_thresh, cv2.COLOR_GRAY2RGB)

results = {}
mot_tracker = Sort() # Object that can sort. Object trackers to track all vehicles

#################
# Load PaddleOCR
#################
ocr = PaddleOCR(use_angle_cls=True, lang='en') # need to run only once to download and load model into memory

# Load two models. One detects cars, the other detects license plates
# coco_model trained on coco dataset. Pretrained model from ultralytics. Used to detect cars.
#################
# load models 
#################
coco_model = YOLO('./models/yolo11n.pt')
license_plate_detector = YOLO('./models/license_plate_detector.pt') 

vehicles = [2, 3, 5, 7] # Detect [car, motorbike, bus, truck]

#################
# load video
#################
cap = cv2.VideoCapture('./sample.mp4') # UK plates - showed up to 92% accuracy
#cap = cv2.VideoCapture('./sample2.mp4') # Florida plates

#################
# Load Live feed 
#################
cam = cv2.VideoCapture(0) # Live video feed

# Get the default frame width and height
frame_width = int(cam.get(cv2.CAP_PROP_FRAME_WIDTH))
frame_height = int(cam.get(cv2.CAP_PROP_FRAME_HEIGHT))

#################
# read frames from live feed
#################
frame_nmr = -1
ret = True #video

#while True: # live
while ret: # video
    frame_nmr += 1
    #ret, frame = cam.read() # live feed
    ret, frame = cap.read() # video feed

    #if ret: # live feed
    if ret and frame_nmr < 1: # video feed
        results[frame_nmr] = {}
        
        #''' # remove this comment to take out vehicle detection (helps with live-feed tests so you don't have to back up so much)
        # detect vehicles
        detections = coco_model(frame)[0]
        detections_ = [] # bounding boxes
        for detection in detections.boxes.data.tolist():
            x1, y1, x2, y2, score, class_id = detection
            if int(class_id) in vehicles:
                detections_.append([x1, y1, x2, y2, score])

        # track vehicles (object tracking)
        track_ids = mot_tracker.update(np.asanyarray(detections_))
        #'''

        # detect license plates
        license_plates = license_plate_detector(frame)[0]
        for license_plate in license_plates.boxes.data.tolist():
            x1, y1, x2, y2, score, class_id = license_plate

            # assign license plate to car
            xcar1, ycar1, xcar2, ycar2, car_id = get_car(license_plate, track_ids) # comment out if vehicle detection has been removed 

            if car_id != -1: # comment out car_id if vehicle detection has been removed
            #if True: #used when commented out car_id

                # crop license plates
                license_plate_crop = frame[int(y1):int(y2), int(x1): int(x2), :]

                # process the image and perform OCR
                processed_image = preprocess_image(license_plate_crop) 
                result = ocr.ocr(processed_image, cls=True)
                
                # display the results by looping through the returned results
                # results are returned as an array of arrays with bounding box coordinates and text + confidence scores
                if result[0] is not None: # Got error without this when frames don't have a license plate.
                    for line in result[0]:
                        text, prob = line[1][0], line[1][1]
                        print(f"Detected text: {text} with probability {prob:.2f}")
                        ##########################
                        # For results array
                        paddle_license_plate_text, paddle_license_text_score = line[1][0], line[1][1]
                        ##########################
                else:
                    paddle_license_plate_text = None # default
                    print(f"No detected license plate. Frame number: ", frame_nmr)

                # Show image
                #'''
                # initialize the image canvas
                fig, ax = plt.subplots(figsize=(15, 15))
                ax.axis('off')  # hide axes
                
                # draw the OCR boxes and texts using the returned results
                for line in result[0]:
                    # extract coordinates and covert them into a NumPy array for OpenCV
                    (top_left, top_right, bottom_right, bottom_left) = line[0]
                    points = np.array([top_left, top_right, bottom_right, bottom_left], dtype=np.int32)

                    # reshape points into the correct format for OpenCV 
                    # (i was having problems with countless errors of formatting so this is from GPT; literally couldn't find an explanation anywhere else)
                    points = points.reshape((-1, 1, 2))

                    # draw the bounding box from the returned coordinates
                    cv2.polylines(processed_image, [points], isClosed=True, color=(0, 255, 0), thickness=2)

                    # convert the top_left coordinates to integers to use them for drawing the text
                    top_left = tuple(map(int, top_left))

                    # using the top_left coordinate, draw the detected text
                    cv2.putText(processed_image, line[1][0], top_left, cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 10)

                # show the license plate image with all the drawn results
                #ax.imshow(processed_image)
                #plt.show()
                #'''

                #if license_plate_text is not None and license_plate_text_score >= 0.7: # Uncomment this and comment the next to only include above 70% confidence scores
                if paddle_license_plate_text is not None:
                    results[frame_nmr][car_id] = {'license_plate': {'text': paddle_license_plate_text, 'text_score': paddle_license_text_score, 'cropped image': license_plate_crop}}
                    
                    #live feed test (take out car_id), comment out line before this
                    #results[frame_nmr][1] = {'license_plate': {'text': paddle_license_plate_text, 'text_score': paddle_license_text_score, 'image': license_plate_crop}}

''' # uncomment this during live testing. Press 'q' to close live video feed and quit program
    # Display the captured frame
    cv2.imshow('Camera', frame)

    # Press 'q' to exit 
    if cv2.waitKey(1) == ord('q'):
        break

# Release the capture
cam.release()
cv2.destroyAllWindows()
'''

# write results
write_csv_wimage(results, './liveFeed_paddle.csv') 
