from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.accounts.serializers import (
    PharmacyTokenObtainPairSerializer,
    RegistrationSerializer,
    UserSerializer,
)


class LoginView(TokenObtainPairView):
    serializer_class = PharmacyTokenObtainPairSerializer


class RegistrationViewSet(viewsets.GenericViewSet):
    permission_classes = (AllowAny,)
    serializer_class = RegistrationSerializer

    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class MeViewSet(viewsets.GenericViewSet):
    permission_classes = (IsAuthenticated,)
    serializer_class = UserSerializer

    def list(self, request):
        return Response(self.get_serializer(request.user).data)
