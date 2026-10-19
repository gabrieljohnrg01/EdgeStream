from django.contrib.auth.models import User
from rest_framework import serializers
from .models import CatalogTitle, WatchlistItem

class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    class Meta:
        model = User
        fields = ["username", "password"]
    def create(self, validated_data):
        return User.objects.create_user(username=validated_data["username"], password=validated_data["password"])

class CatalogTitleSerializer(serializers.ModelSerializer):
    poster_url = serializers.ReadOnlyField()
    backdrop_url = serializers.ReadOnlyField()
    class Meta:
        model = CatalogTitle
        fields = ["id", "tmdb_id", "media_type", "title", "original_title", "overview", "poster_path", "backdrop_path", "poster_url", "backdrop_url", "release_date", "original_language", "vote_average", "vote_count", "popularity", "genre_ids", "sections", "last_synced"]

class WatchlistItemSerializer(serializers.ModelSerializer):
    catalog_title = CatalogTitleSerializer(read_only=True)
    catalog_title_id = serializers.PrimaryKeyRelatedField(source="catalog_title", queryset=CatalogTitle.objects.all(), write_only=True)
    class Meta:
        model = WatchlistItem
        fields = ["id", "catalog_title", "catalog_title_id", "added_at"]
        read_only_fields = ["id", "added_at"]

class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)
