from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from .models import BookingModel, PaymentModel
from django.utils import timezone
from datetime import timedelta


@shared_task
def verify_payment_and_confirm(payment_id):

    try:
        with transaction.atomic():

            payment = (
                PaymentModel.objects.select_for_update()
                .select_related("booking__user", "booking__car")
                .get(id=payment_id)
            )

            booking = BookingModel.objects.select_for_update().get(
                id=payment.booking_id
            )

            if booking.status != "pending":
                return "Booking is not pending"

            if payment.status == "rejected":
                return "Payment was rejected"

            if not payment.screenshot:
                return "Payment screenshot missing"

            if not payment.screenshot.storage.exists(payment.screenshot.name):
                return "Screenshot file does not exist"

            if payment.amount != booking.total_price:
                return "Payment amount does not match"

            # Demo verification only
            payment.status = "paid"
            payment.save(update_fields=["status"])

            booking.status = "confirmed"
            booking.save(update_fields=["status"])

            transaction.on_commit(lambda: send_booking_confirmation.delay(booking.id))

        return f"Booking {booking.id} confirmed successfully"

    except PaymentModel.DoesNotExist:
        return "Payment not found"


def send_customer_email(booking, subject, message):
    if not booking.user.email:
        return

    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[booking.user.email],
        fail_silently=False,
    )


def send_customer_push(booking, title, message):
    from webpush import send_user_notification

    send_user_notification(
        user=booking.user,
        payload={
            "head": title,
            "body": message,
            "url": "/booking/history/",
        },
        ttl=1000,
    )


@shared_task
def send_booking_confirmation(booking_id):
    try:
        booking = BookingModel.objects.select_related("user", "car").get(
            id=booking_id, status="confirmed"
        )

    except BookingModel.DoesNotExist:
        return "Confirmed booking not found"

    subject = "Your Car Booking is Confirmed!"

    message = (
        f"Hello {booking.user.username},\n\n"
        f"Your booking for {booking.car.car_name} is confirmed.\n"
        f"Pickup: {booking.pickup_datetime}\n"
        f"Return: {booking.return_datetime}\n"
        f"Total: {booking.total_price}\n\n"
        "Thank you for choosing us!"
    )

    send_customer_email(booking, subject, message)

    try:
        send_customer_push(
            booking,
            "Booking Confirmed!",
            f"Your {booking.car.car_name} booking is confirmed.",
        )
    except Exception as e:
        print("Confirmation Web Push Error:", repr(e))

    return f"Confirmation notification sent for booking {booking_id}"


@shared_task
def pickup_reminder_task():
    now = timezone.now()

    # Remind 24 hours before pickup
    start = now + timedelta(hours=24)
    end = start + timedelta(minutes=1)

    bookings = BookingModel.objects.filter(
        status="confirmed",
        pickup_reminder_sent=False,
        pickup_datetime__gte=start,
        pickup_datetime__lt=end,
    ).select_related("user", "car")

    for booking in bookings:
        subject = "Your Car Pickup Reminder"

        message = (
            f"Hello {booking.user.username},\n\n"
            f"Reminder: Your {booking.car.car_name} pickup "
            f"is scheduled for {booking.pickup_datetime}.\n"
            "Please be ready on time."
        )

        try:
            send_customer_email(booking, subject, message)

            try:
                send_customer_push(
                    booking,
                    "Pickup Reminder",
                    f"Your car pickup is scheduled for {booking.pickup_datetime}.",
                )
            except Exception as e:
                print("Pickup Web Push Error:", repr(e))

            booking.pickup_reminder_sent = True
            booking.save(update_fields=["pickup_reminder_sent"])

        except Exception as e:
            print("Pickup Email Error:", repr(e))


@shared_task
def return_reminder_task():
    now = timezone.now()

    # Remind 2 hours before return
    start = now + timedelta(hours=2)
    end = start + timedelta(minutes=1)

    bookings = BookingModel.objects.filter(
        status="confirmed",
        return_reminder_sent=False,
        return_datetime__gte=start,
        return_datetime__lt=end,
    ).select_related("user", "car")

    for booking in bookings:
        subject = "Your Car Return Reminder"

        message = (
            f"Hello {booking.user.username},\n\n"
            f"Reminder: Please return your {booking.car.car_name} "
            f"by {booking.return_datetime}.\n"
            "Thank you!"
        )

        try:
            send_customer_email(booking, subject, message)

            try:
                send_customer_push(
                    booking,
                    "Return Reminder",
                    f"Please return your car by {booking.return_datetime}.",
                )
            except Exception as e:
                print("Return Web Push Error:", repr(e))

            booking.return_reminder_sent = True
            booking.save(update_fields=["return_reminder_sent"])

        except Exception as e:
            print("Return Email Error:", repr(e))


@shared_task
def overdue_booking_task():
    now = timezone.now()

    bookings = BookingModel.objects.filter(
        status="confirmed",
        return_datetime__lt=now,
        overdue_notified=False,
    ).select_related("user", "car")

    for booking in bookings:
        subject = "Car Return Overdue"

        message = (
            f"Hello {booking.user.username},\n\n"
            f"Your return time for {booking.car.car_name} "
            f"was {booking.return_datetime}.\n"
            "Please contact us immediately."
        )

        try:
            send_customer_email(booking, subject, message)

            try:
                send_customer_push(
                    booking,
                    "Car Return Overdue",
                    f"Your {booking.car.car_name} return time has passed.",
                )
            except Exception as e:
                print("Overdue Web Push Error:", repr(e))

            booking.overdue_notified = True
            booking.save(update_fields=["overdue_notified"])

        except Exception as e:
            print("Overdue Email Error:", repr(e))

    return f"Checked overdue bookings at {now}"
