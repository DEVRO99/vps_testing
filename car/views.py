from django.shortcuts import render, redirect, get_object_or_404
from car.models import (
    CarModel,
    BrandModel,
    BookingModel,
    Location,
    PaymentModel,
    WishlistModel,
    ReviewModel,
)
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib import messages
import math
from datetime import datetime
from django.utils import timezone
from .form import RegisterForm
from django.contrib.admin.views.decorators import staff_member_required
from django.core.mail import send_mail
from django.conf import settings
from datetime import timedelta
from .models import OTPModel
from .form import RegisterForm
import secrets
from webpush import send_user_notification
from django.contrib.auth import get_user_model
from django.db import transaction
from .tasks import verify_payment_and_confirm
from django.db import transaction


def Index(request):
    brands = BrandModel.objects.all()
    brand_id = request.GET.get("brand")

    if brand_id:
        selected_brand = BrandModel.objects.get(id=brand_id)
    else:
        selected_brand = brands.first()

    print("Selected brand:", selected_brand)
    print("Selected brand ID:", selected_brand.id)

    cars = CarModel.objects.filter(car_brand_id=selected_brand.id)

    print("Cars:", cars)

    return render(
        request,
        "index.html",
        {
            "brands": brands,
            "cars": cars,
            "selected_brand": selected_brand,
        },
    )


@staff_member_required
def CarList(request):
    brands = BrandModel.objects.all()
    cars = CarModel.objects.all()
    return render(request, "car_list.html", {"cars": cars, "brands": brands})


def CarCreate(request):
    brands = BrandModel.objects.all().order_by("-created_at")

    if request.method == "GET":
        return render(request, "car_create.html", {"brands": brands})

    if request.method == "POST":

        car_name = request.POST.get("car_name")
        car_brand = request.POST.get("car_brand")
        price_per_day = request.POST.get("price_per_day")
        seats = request.POST.get("seats")
        transmission = request.POST.get("transmission")
        fuel_type = request.POST.get("fuel_type")
        max_speed = request.POST.get("max_speed")
        image = request.FILES.get("image")

        # Create car
        car = CarModel.objects.create(
            car_name=car_name,
            price_per_day=price_per_day,
            seats=seats,
            transmission=transmission,
            fuel_type=fuel_type,
            max_speed=max_speed,
            image=image,
            car_brand_id=car_brand,
        )

        # Web Push Notification
        try:
            send_user_notification(
                user=request.user,
                payload={
                    "head": "New Car Added!",
                    "body": f"{car.car_name} has been added successfully.",
                    "url": "/",
                },
                ttl=1000,
            )

            print("Web Push sent successfully!")

        except Exception as e:
            print("Web Push Error:", repr(e))

        messages.success(request, "Car created successfully!")

        return redirect("/")


def CarUpdate(request, pk):
    brands = BrandModel.objects.all().order_by("-created_at")
    car = CarModel.objects.get(id=pk)

    if request.method == "GET":
        return render(request, "car_update.html", {"car": car, "brands": brands})

    if request.method == "POST":
        car_name = request.POST.get("car_name")
        car_brand = request.POST.get("car_brand")
        price_per_day = request.POST.get("price_per_day")
        seats = request.POST.get("seats")
        transmission = request.POST.get("transmission")
        fuel_type = request.POST.get("fuel_type")
        max_speed = request.POST.get("max_speed")
        image = request.FILES.get("image")

        car.car_name = car_name
        car.car_brand_id = car_brand
        car.price_per_day = price_per_day
        car.seats = seats
        car.transmission = transmission
        car.fuel_type = fuel_type
        car.max_speed = max_speed

        if image:
            car.image.delete()
            car.image = image

        car.save()
        messages.success(request, "Car updated successfully")

        return redirect("/")


def CarDelete(request, pk):
    car = CarModel.objects.get(id=pk)
    if request.method == "GET":
        return render(request, "car_delete.html", {"car": car})
    if request.method == "POST":
        if car.image:
            car.image.delete()
        car.delete()
        messages.success(request, "Car deleted successfully")
        return redirect("/car/list/")


def BrandCreate(request):
    if request.method == "GET":
        return render(request, "brand_create.html")
    if request.method == "POST":
        name = request.POST.get("name")
        brand = BrandModel.objects.create(name=name)
        brand.save()
        return redirect("/car/list/")


def BrandUpdate(request, pk):
    brand = BrandModel.objects.get(id=pk)
    if request.method == "GET":
        return render(request, "brand_update.html", {"brand": brand})
    if request.method == "POST":
        name = request.POST.get("name")
        brand.name = name
        brand.save()
        return redirect("/car/list/")


def BrandDelete(request, pk):
    brand = BrandModel.objects.get(id=pk)
    if request.method == "GET":
        return render(request, "brand_delete.html", {"brand": brand})
    if request.method == "POST":
        brand.delete()
        return redirect("/car/list/")


def is_car_available(car, pickup, return_):
    return not BookingModel.objects.filter(
        car=car,
        status="confirmed",
        pickup_datetime__lt=return_,
        return_datetime__gt=pickup,
    ).exists()


# Send notification to all active admin/staff users
def send_admin_booking_notification(booking):

    User = get_user_model()

    admins = User.objects.filter(is_staff=True, is_active=True)

    payload = {
        "head": "New Booking Received!",
        "body": (f"{booking.user.username} booked " f"{booking.car.car_name}."),
        "url": "/admin-dashboard/",
    }

    for admin in admins:
        try:
            send_user_notification(
                user=admin,
                payload=payload,
                ttl=1000,
            )
        except Exception as e:
            print(f"Web Push Error for admin {admin.username}:", repr(e))


@login_required
def BookCar(request, pk):
    car = get_object_or_404(CarModel, id=pk)
    locations = Location.objects.all()

    if request.method == "POST":
        location_id = request.POST.get("location")
        location = get_object_or_404(Location, id=location_id)

        pickup_date = request.POST.get("pickup_date")
        pickup_time = request.POST.get("pickup_time")

        return_date = request.POST.get("return_date")
        return_time = request.POST.get("return_time")

        pickup_datetime = timezone.make_aware(
            datetime.strptime(f"{pickup_date} {pickup_time}", "%Y-%m-%d %H:%M")
        )

        return_datetime = timezone.make_aware(
            datetime.strptime(f"{return_date} {return_time}", "%Y-%m-%d %H:%M")
        )

        if pickup_datetime < timezone.now():
            return render(
                request,
                "booking.html",
                {
                    "car": car,
                    "locations": locations,
                    "error": "Pickup cannot be in the past",
                },
            )

        if return_datetime <= pickup_datetime:
            return render(
                request,
                "booking.html",
                {
                    "car": car,
                    "locations": locations,
                    "error": "Return must be after pickup",
                },
            )

        if not is_car_available(car, pickup_datetime, return_datetime):
            return render(
                request,
                "booking.html",
                {
                    "car": car,
                    "locations": locations,
                    "error": "Car already booked",
                },
            )

        diff = (return_datetime - pickup_datetime).total_seconds()

        days = math.ceil(diff / (60 * 60 * 24))

        total_price = days * car.price_per_day
        total_price += location.extra_price

        # Create booking only
        booking = BookingModel.objects.create(
            car=car,
            user=request.user,
            location=location,
            pickup_datetime=pickup_datetime,
            return_datetime=return_datetime,
            total_price=total_price,
            status="pending",
        )

        # Redirect to payment page
        return redirect(f"/payment/{booking.id}/")

    return render(
        request,
        "booking.html",
        {
            "car": car,
            "locations": locations,
        },
    )


@login_required
def cancel_booking_user(request, pk):

    if request.method != "POST":
        return redirect("booking_history")

    with transaction.atomic():

        booking = get_object_or_404(
            BookingModel.objects.select_for_update(), id=pk, user=request.user
        )

        if booking.status == "pending":
            booking.status = "cancelled"
            booking.save(update_fields=["status"])

            messages.success(request, "Booking cancelled successfully.")

        else:
            messages.warning(request, "Only pending bookings can be cancelled.")

    return redirect("booking_history")


@login_required
def payment_page(request, booking_id):

    if request.method == "POST":

        with transaction.atomic():

            booking = get_object_or_404(
                BookingModel.objects.select_for_update(),
                id=booking_id,
                user=request.user,
            )

            # Prevent duplicate payment
            if PaymentModel.objects.filter(booking=booking).exists():
                return redirect("/booking/history/")

            # Only pending bookings can be paid
            if booking.status != "pending":
                messages.error(request, "This booking cannot be paid.")
                return redirect("/booking/history/")

            method = request.POST.get("method")
            screenshot = request.FILES.get("screenshot")

            if not method or method not in dict(PaymentModel.PAYMENT_METHODS):
                messages.error(request, "Please select a valid payment method.")
                return redirect(request.path)

            if not screenshot:
                messages.error(request, "Please upload payment screenshot.")
                return redirect(request.path)

            payment = PaymentModel.objects.create(
                booking=booking,
                method=method,
                amount=booking.total_price,
                screenshot=screenshot,
                status="pending",
            )

            # Trigger Celery after database commit
            transaction.on_commit(lambda: verify_payment_and_confirm.delay(payment.id))

        # Notify admins after payment submission
        try:
            send_admin_booking_notification(booking)
        except Exception as e:
            print("Admin Web Push Error:", repr(e))

        messages.success(
            request, "Payment submitted successfully. Your booking is being processed."
        )

        return redirect("/booking/history/")

    booking = get_object_or_404(BookingModel, id=booking_id, user=request.user)

    if booking.status != "pending":
        messages.error(request, "This booking cannot be paid.")
        return redirect("/booking/history/")

    if PaymentModel.objects.filter(booking=booking).exists():
        return redirect("/booking/history/")

    return render(request, "payment.html", {"booking": booking})


@login_required
def booking_history(request):
    bookings = BookingModel.objects.filter(user=request.user).order_by("-created_at")

    return render(request, "booking_history.html", {"bookings": bookings})


# =====================================================================
def register(request):

    if request.method == "POST":

        form = RegisterForm(request.POST)

        if form.is_valid():

            # Create user but don't activate yet
            user = form.save(commit=False)
            user.is_active = False
            user.save()

            # Generate 6-digit OTP
            otp_code = f"{secrets.randbelow(1000000):06d}"

            # Set OTP expiry to 5 minutes
            expires_at = timezone.now() + timedelta(minutes=5)

            # Save OTP
            OTPModel.objects.update_or_create(
                user=user,
                defaults={
                    "otp_code": otp_code,
                    "expires_at": expires_at,
                },
            )

            # Send OTP to user's email
            send_mail(
                subject="Your Verification Code",
                message=f"Your OTP is {otp_code}. It expires in 5 minutes.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
            )

            messages.success(request, "OTP sent to your email.")
            return redirect("verify_otp")

        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)

    else:
        form = RegisterForm()

    return render(request, "auth/register.html", {"form": form})


def verify_otp(request):

    if request.method == "POST":

        email = request.POST.get("email")
        otp_code = request.POST.get("otp_code")

        try:
            user = User.objects.get(email=email, is_active=False)
            otp = OTPModel.objects.get(user=user)

            if otp.is_expired():
                otp.delete()
                messages.error(request, "OTP has expired. Please register again.")
                return redirect("register")

            if otp.otp_code == otp_code:

                user.is_active = True
                user.save()

                otp.delete()

                messages.success(
                    request, "Email verified successfully. You can now login."
                )
                return redirect("login")

            else:
                messages.error(request, "Invalid OTP.")

        except (User.DoesNotExist, OTPModel.DoesNotExist):
            messages.error(request, "Invalid verification details.")

    return render(request, "auth/verify_otp.html")


# =====================================================================


def user_login(request):

    if request.method == "POST":

        email = request.POST.get("email")
        password = request.POST.get("password")
        next_url = request.POST.get("next")

        try:
            user_obj = User.objects.get(email=email)

            user = authenticate(request, username=user_obj.username, password=password)

        except:
            user = None

        if user is not None:

            login(request, user)

            messages.success(request, "Login successful")

            if next_url:
                return redirect(next_url)

            return redirect("/")

        else:

            messages.error(request, "Invalid email or password")

            return redirect("login")

    return render(request, "auth/login.html")


def user_logout(request):
    logout(request)
    return redirect("/")


@staff_member_required
def admin_dashboard(request):
    bookings = BookingModel.objects.all().order_by("-created_at")
    return render(request, "dashboard/admin_dashboard.html", {"bookings": bookings})


@staff_member_required
# 1. Notification function (NO decorator)
def send_booking_notification(user, title, message):

    payload = {"head": title, "body": message, "url": "/"}

    send_user_notification(user=user, payload=payload, ttl=1000)


# Admin confirmation view


@staff_member_required
def confirm_booking(request, pk):

    if request.method != "POST":
        return redirect("admin_dashboard")

    booking = get_object_or_404(BookingModel, id=pk)

    if booking.status == "pending":

        booking.status = "confirmed"
        booking.save()

        try:
            send_booking_notification(
                booking.user,
                "Booking Confirmed!",
                f"Your booking for {booking.car.car_name} has been confirmed.",
            )
        except Exception as e:
            print("Web Push Error:", e)

        messages.success(request, "Booking confirmed successfully.")

    else:
        messages.warning(request, "This booking is already processed.")

    return redirect("admin_dashboard")


@staff_member_required
def cancel_booking(request, pk):
    booking = BookingModel.objects.get(id=pk)
    booking.status = "cancelled"
    booking.save()
    return redirect("admin_dashboard")


@login_required
def compare_cars(request):

    id1 = request.GET.get("car1")
    id2 = request.GET.get("car2")

    car1 = get_object_or_404(CarModel, id=id1)
    car2 = get_object_or_404(CarModel, id=id2)

    return render(
        request,
        "compare.html",
        {
            "car1": car1,
            "car2": car2,
        },
    )


@login_required
def add_to_wishlist(request, car_id):

    car = get_object_or_404(CarModel, id=car_id)

    WishlistModel.objects.get_or_create(user=request.user, car=car)

    return redirect("/")


@login_required
def remove_wishlist(request, car_id):

    car = get_object_or_404(CarModel, id=car_id)

    WishlistModel.objects.filter(user=request.user, car=car).delete()

    return redirect("/wishlist/")


@login_required
def wishlist_page(request):

    wishlist = WishlistModel.objects.filter(user=request.user)

    return render(request, "wishlist.html", {"wishlist": wishlist})


@login_required
def add_review(request):

    if request.method == "POST":

        message = request.POST.get("message")

        ReviewModel.objects.create(user=request.user, message=message)

        messages.success(request, "Review added successfully")

        return redirect("/")


def review_page(request):

    reviews = ReviewModel.objects.all().order_by("-id")

    return render(request, "reviews.html", {"reviews": reviews})
