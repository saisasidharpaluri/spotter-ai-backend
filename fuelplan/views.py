from django.http import JsonResponse


def health(request):
    if request.method != "GET":
        return JsonResponse({"error": {"code": "method_not_allowed", "message": "Use GET."}}, status=405)
    return JsonResponse({"status": "ok"})
